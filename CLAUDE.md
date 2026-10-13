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
  the scripts, `dialogs.py` the settings dialog, `positions.py` where
  navigation stopped in each file, `session.py` the connection's life (retries,
  stats thread, disconnect), `tiktok_adapter.py` everything that knows
  TikTokLive (loading it, the client, library events into `events.py`'s plain
  ones), `pipeline.py` what is done with each event (duplicate checks, lines,
  counters, announcements),
  `settings.py` the `Settings` object and `tiktokLiveReader.ini`, `store.py`
  the session's text files (every read and write of them), `announcer.py`
  sounds and speech (the speech buffer, its reader, the sound queue),
  `likes.py` each person's likes summed until a 10 s pause, `i18n.py` the
  one `_` every module imports, `vendor.py` keeps `lib/` private, the
  vendored TikTokLive 6.6.5 and its pure-Python dependencies).
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

Style is the NVDA add-on template's (`pyproject.toml`: tabs, line length
110), with ruff 0.14.5 from `artifacts\tools\ruff` on our code only (`lib/`
is excluded; the template's own files are left as published). Keep a
`# Translators:` comment on the line right above its string after
formatting.

```
artifacts\tools\ruff\ruff.exe format addon/globalPlugins/TiktokLiveReader tests tools sandbox
artifacts\tools\ruff\ruff.exe check addon/globalPlugins/TiktokLiveReader tests tools sandbox
```

Windows Sandbox runs one instance at a time and the BST Radio project uses it
too: close it (`sandbox\Run-Sandbox.ps1 -Stop`) when done and tell that
session.

## Current work

Version 2.0, see `docs/dev/plan.md`.
