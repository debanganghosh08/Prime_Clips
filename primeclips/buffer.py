"""The replay buffer: the reason Prime Clips is fast.

ffmpeg stream-copies the live stream into tiny 2-second MPEG-TS segments and we keep
a rolling window of the last N minutes on disk. A clip is just "concatenate the
segments that cover [t0, t1]", with no decoding and no encoding. Cutting a 30 s clip
from a 1080p60 stream takes well under a second and costs almost no CPU."""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config
from .ffmpeg import popen_kwargs, run, which
from .ingest import Source

log = logging.getLogger("primeclips.buffer")


@dataclass
class Segment:
    path: Path
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class ReplayBuffer:
    def __init__(self, cfg: Config, source: Source, workdir: Path,
                 on_segment: Callable[[Segment], None] | None = None,
                 on_exit: Callable[[str | None], None] | None = None):
        self.cfg = cfg
        self.source = source
        self.dir = workdir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.on_segment = on_segment
        self.on_exit = on_exit
        self.segments: list[Segment] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._base: float | None = None
        self._last_wall = 0.0
        self._pins: dict[str, float] = {}  # job id -> earliest stream time still needed
        self.error: str | None = None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        ffmpeg = which(self.cfg.ffmpeg) or self.cfg.ffmpeg
        pattern = str(self.dir / "seg_%06d.ts")
        csv = self.dir / "segments.csv"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "+genpts+discardcorrupt",
               *self.source.input_args,
               "-map", "0:v:0?", "-map", "1:a:0?" if self.source.input_args.count("-i") > 1 else "0:a:0?",
               "-c", "copy", "-f", "segment", "-segment_time", str(self.cfg.segment_seconds),
               "-segment_format", "mpegts", "-segment_list", str(csv),
               "-segment_list_type", "csv", "-segment_list_size", "0", pattern]
        kw = popen_kwargs(self.cfg.low_priority)
        stdin = subprocess.DEVNULL
        if self.source.upstream:
            up = subprocess.Popen(self.source.upstream, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, **kw)
            self._procs.append(up)
            stdin = up.stdout
            threading.Thread(target=self._drain, args=(up, "upstream"), daemon=True).start()
        ff = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, **kw)
        self._procs.append(ff)
        threading.Thread(target=self._drain, args=(ff, "ffmpeg"), daemon=True).start()
        threading.Thread(target=self._watch, args=(csv, ff), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        for p in reversed(self._procs):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def cleanup_when_idle(self, timeout: float = 120.0) -> None:
        """Delete the segment folder once no pending cut still needs it."""
        def _go() -> None:
            deadline = time.time() + timeout
            while self._pins and time.time() < deadline:
                time.sleep(1)
            shutil.rmtree(self.dir, ignore_errors=True)
        threading.Thread(target=_go, daemon=True).start()

    @property
    def running(self) -> bool:
        return not self._stop.is_set() and bool(self._procs) and self._procs[-1].poll() is None

    # ---------------------------------------------------------------- internals
    def _drain(self, proc: subprocess.Popen, name: str) -> None:
        tail: list[str] = []
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode(errors="replace").strip()
            if line:
                tail = (tail + [line])[-5:]
                log.debug("[%s] %s", name, line)
        if not self._stop.is_set() and tail and proc.wait() != 0:
            self.error = f"{name}: {tail[-1]}"

    def _watch(self, csv: Path, ff: subprocess.Popen) -> None:
        pos = 0  # byte offset: only read what ffmpeg appended (cheap even on 10-hour streams)
        while not self._stop.is_set():
            ended = ff.poll() is not None
            if csv.exists():
                with open(csv, "rb") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                done = chunk.rfind(b"\n") + 1  # only complete lines
                pos += done
                lines = chunk[:done].decode("utf-8", errors="replace").splitlines()
                for line in lines:
                    parts = line.rsplit(",", 2)
                    if len(parts) != 3:
                        continue
                    try:
                        start, end = float(parts[1]), float(parts[2])
                    except ValueError:
                        continue
                    if self._base is None:
                        self._base = start
                    seg = Segment(self.dir / parts[0], start - self._base, end - self._base)
                    with self._lock:
                        self.segments.append(seg)
                        self._last_wall = time.time()
                    if self.on_segment:
                        try:
                            self.on_segment(seg)
                        except Exception:
                            log.exception("segment callback failed")
                self._prune()
            if ended:
                break
            self._stop.wait(0.25)
        if not self._stop.is_set():
            self._stop.set()
            if self.on_exit:
                self.on_exit(self.error or ("stream ended" if ff.returncode == 0 else f"ffmpeg exited ({ff.returncode})"))

    def _prune(self) -> None:
        keep = self.cfg.buffer_minutes * 60
        with self._lock:
            if not self.segments:
                return
            horizon = self.segments[-1].end - keep
            if self._pins:
                horizon = min(horizon, min(self._pins.values()))
            while self.segments and self.segments[0].end < horizon:
                old = self.segments.pop(0)
                try:
                    old.path.unlink(missing_ok=True)
                except OSError:
                    pass

    # ---------------------------------------------------------------- public api
    @property
    def latest(self) -> float:
        with self._lock:
            return self.segments[-1].end if self.segments else 0.0

    @property
    def earliest(self) -> float:
        with self._lock:
            return self.segments[0].start if self.segments else 0.0

    @property
    def seconds(self) -> float:
        return max(0.0, self.latest - self.earliest)

    def now(self) -> float:
        """Best estimate of the current stream time (includes the segment being written)."""
        with self._lock:
            if not self.segments:
                return 0.0
            return self.segments[-1].end + min(time.time() - self._last_wall, self.cfg.segment_seconds * 2)

    def pin(self, key: str, t: float) -> None:
        with self._lock:
            self._pins[key] = t

    def unpin(self, key: str) -> None:
        with self._lock:
            self._pins.pop(key, None)

    def wait_until(self, t: float, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.latest >= t:
                return True
            if not self.running:
                return self.latest > 0
            time.sleep(0.2)
        return self.latest >= t

    def cut(self, t0: float, t1: float, dst: Path) -> tuple[float, float]:
        """Stream-copy [t0, t1] into dst (.mp4). Snaps the start to a segment boundary
        (always a keyframe) so the clip never begins with grey/smeared frames."""
        with self._lock:
            segs = [s for s in self.segments if s.end > t0 and s.start < t1 and s.path.exists()]
        if not segs:
            raise RuntimeError("nothing in the buffer for that time range yet")
        start = segs[0].start
        end = min(t1, segs[-1].end)
        lst = dst.with_suffix(".txt")
        lst.write_text("".join(f"file '{s.path.as_posix()}'\n" for s in segs), encoding="utf-8")
        try:
            run([which(self.cfg.ffmpeg) or self.cfg.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "concat", "-safe", "0", "-i", lst, "-t", f"{end - start:.3f}",
                 "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero",
                 "-movflags", "+faststart", dst], timeout=120)
        finally:
            lst.unlink(missing_ok=True)
        return start, end
