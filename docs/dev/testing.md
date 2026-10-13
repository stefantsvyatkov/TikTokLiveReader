# Testing

## Unit and replay tests (host, no NVDA)

`tests/support.py` mounts the add-on as package `tiktokAddon` with stand-ins
for NVDA's modules (`ui.message` is recorded in `support.spoken`, message
dialogs in `support.dialogs`). `NVDAState.WritePaths.configDir` and every file
the add-on keeps in its own folder point into a temporary folder.

`tests/feed.py` builds real-format TikTok messages and `run_session` runs them
through the add-on's own connection thread (`client.connect`) with a
`TikTokLiveClient` subclass that replays instead of connecting: real library
decoding, real event dispatch, real handlers. The sound manager is replaced by
a recorder without delays; speech is read back from the speech buffer. A
number among the frames is a pause. `past_grace_period` skips the 10 second
silence after connecting; `settle_likes` lets the like timers fire.

- `test_feed.py` - the feed decodes like a live connection.
- `test_pipeline.py` - behaviour to keep.
- `test_known_issues.py` - 1.8 behaviour believed wrong, one test per
  finding.

## Still to build

- Recorder: raw frames of public lives to `artifacts/recordings/` (never
  committed; committed fixtures are anonymized).
- Library comparison: the same recordings decoded by 6.6.5 and 7.0.1.
- Windows Sandbox with portable NVDA 2026.1.1, 2026.2, 2026.3beta4 and the
  add-on installed, silent synthesizer, speech read from NVDA's log, the
  vendored TikTokLive swapped for a replaying one. Pattern: BST Radio's
  `Windows/sandbox` (persistent sandbox, request file, heartbeat, minimized
  without focus, muted).
