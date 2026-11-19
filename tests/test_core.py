"""Fast tests: no ffmpeg, no network.  Run: python -m pytest -q"""
from pathlib import Path

from primeclips.captions import write_ass
from primeclips.detector import HypeDetector
from primeclips.ingest import detect
from primeclips.render import filter_graph
from primeclips.vod import loudness_moments


def test_detect_platforms():
    assert detect("https://www.twitch.tv/SomeStreamer") == ("twitch", "somestreamer")
    assert detect("https://kick.com/abc") == ("kick", "abc")
    assert detect("https://www.youtube.com/@creator/live") == ("youtube", "creator")


def test_audio_spike_triggers_once():
    d = HypeDetector(threshold=60, cooldown=30)
    t = 0.0
    while t < 60:  # quiet baseline
        d.add_audio(t, -40.0 + (t % 2))
        t += 0.5
    assert d.tick(60)[1] is None
    for i in range(6):  # sudden scream
        d.add_audio(60 + i * 0.5, -6.0)
    score, reason = d.tick(63)
    assert score >= 60 and reason and "audio" in reason
    assert d.tick(64)[1] is None  # cooldown


def test_chat_explosion_triggers():
    d = HypeDetector(threshold=60, cooldown=30)
    for i in range(120):  # ~0.5 msg/s baseline
        d.add_chat(i, "hello")
    for i in range(40):
        d.add_chat(121 + i * 0.1, "KEKW CLIP IT")
    score, reason = d.tick(125)
    assert reason and "chat" in reason, (score, reason)


def test_loudness_moments_finds_peaks():
    levels = [-40.0] * 600
    for i in range(200, 205):
        levels[i] = -5.0
    for i in range(450, 455):
        levels[i] = -8.0
    peaks = sorted(int(p) for p, _ in loudness_moments(levels, 2, 30))
    assert abs(peaks[0] - 203) <= 3 and abs(peaks[1] - 453) <= 3


def test_filter_graphs_are_well_formed():
    for layout in ("vertical-blur", "streamer", "gaming", "crop", "landscape"):
        g = filter_graph(layout, "captions.ass")
        assert g.endswith("[v]") and "subtitles=f=captions.ass" in g and "setpts=PTS-STARTPTS" in g


def test_ass_writer(tmp_path: Path):
    out = write_ass([(0.0, 0.4, "no"), (0.4, 0.8, "way"), (0.9, 1.3, "bro")], tmp_path / "c.ass", pos=(540, 825))
    text = out.read_text(encoding="utf-8")
    assert text.count("Dialogue:") == 3 and "WAY" in text and r"\pos(540,825)" in text and r"\t(0,140" in text


def test_spread_spacing():
    levels = [-40.0] * 1000
    for c in (100, 140, 600):
        for i in range(c, c + 4):
            levels[i] = -5.0
    peaks = sorted(int(p) for p, _ in loudness_moments(levels, 3, 30, spacing=200))
    assert len(peaks) >= 2 and all(b - a >= 200 for a, b in zip(peaks, peaks[1:]))
