# Contributing to Prime Clips

Thanks for helping make clipping faster. Bug reports, ideas and pull requests are all welcome.

## Setup

```bash
git clone https://github.com/debanganghosh08/Prime_Clips.git
cd Prime_Clips
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1    macOS/Linux: source .venv/bin/activate
pip install -e ".[all]"
primeclips doctor
primeclips serve --open
```

You need Python 3.10+ and ffmpeg on your PATH.

## Reporting bugs

Open an issue with your OS, Python version, `primeclips doctor` output, the command you ran, and the error. Run with `primeclips -v ...` for debug logs. Please remove webhook URLs and API keys before pasting anything.

## Pull requests

- Keep changes focused; one idea per PR.
- Keep the core path light: stream copy where possible, one render at a time, no heavy always-on work.
- New settings should be `PRIMECLIPS_*` env vars and added to `.env.example` and the README table.
- If you add or change an HTTP route, update `docs/API.md`.
- Mark anything you could not test (a platform, a GPU, an upload target) as experimental in the docs.
- Do not add third-party game or streamer footage, logos or other copyrighted assets to the repo.

Good first areas are on the README roadmap: Kick chat, more upload targets, per-game detectors.

## License

By contributing you agree your work is released under the [MIT License](LICENSE).
