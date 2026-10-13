# TikTok Live Reader

NVDA add-on that connects to a TikTok LIVE through the unofficial TikTokLive
library and turns comments, gifts, likes, follows, shares, visitors and guest
requests into text files, speech and sounds. Published in the NVDA Add-on
Store. The user is Bulgarian; answer in Bulgarian and address them with "ти".

## Rules

- Never change user-facing strings (msgids) or user documentation
  (`addon/doc/`, `README.md`, translations); the user maintains them.
- Commit messages: one short English line in the imperative, like the history.
- Explanations belong in `docs/dev/`, not in code comments; comment only what
  will genuinely help later.
- Work on `main`; release tags are the rollback points.

## Layout

- `addon/globalPlugins/TiktokLiveReader/` - the add-on (`globalPlugin.py`
  scripts and settings dialog, `client.py` connection and event handling,
  `settings.py` the `Settings` object and `tiktokLiveReader.ini`, `i18n.py`
  the one `_` every module imports, `vendor_loader.py` isolates `lib/`, the
  vendored TikTokLive 6.6.5 and its pure-Python dependencies). New and
  rewritten modules use tabs (NVDA style); the old ones are reformatted in one
  commit at the end of phase 2.
- `tests/` - unittest suite run outside NVDA (`support.py` stands in for NVDA,
  `feed.py` replays real-format TikTok messages through the add-on's own
  connection thread).
- `docs/dev/` - plan, findings, library notes, testing notes.
- `artifacts/` (gitignored) - NVDA installers, portable Python 3.13, sandbox
  staging, live recordings.

## Running tests

```
artifacts\tools\python313\python.exe -X utf8 -m unittest discover -s tests -t .
```

Python 3.13 x64 matches NVDA 2026.x. The portable copy is the embeddable
distribution (copied from the Sonos controller project); it runs the suite
without installing anything.

## Current work

Version 2.0, see `docs/dev/plan.md`.
