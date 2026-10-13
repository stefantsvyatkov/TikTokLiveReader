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

`feed.replaying(...)` is the same replay as a context manager; with
`end="hold"` the connection stays open until the test sets `release`, and,
like the real client in 1.8, switching the add-on off does not end it (F1).

- `test_feed.py` - the feed decodes like a live connection.
- `test_plugin.py` - the scripts: on/off, navigation, positions, clearing,
  toggles, archiving, settings file.
- `test_pipeline.py` - behaviour to keep.
- `test_known_issues.py` - 1.8 behaviour believed wrong, one test per
  finding.

The suite takes about 70 s, most of it the 3 s freeze of F27 in every test
that switches off a held session.

Run one module with
`-m unittest discover -s tests -t . -p test_plugin.py` (the portable Python
does not put the working folder on `sys.path` for `-m unittest tests.x`).

## Live recordings and the library comparison

- `tools/record_live.py <user> <minutes>` records a public live as raw
  messages (method, payload, ids, history flag, frame) to
  `artifacts/recordings/`, through the add-on's vendored library and vendor
  loader. Recordings hold real names: never committed; committed fixtures are
  anonymized.
- `tools/decode_recording.py <recording> <lib> <out>` decodes a recording
  with one copy of TikTokLive (run each library in its own interpreter) into
  the fields the add-on reads, by meaning, so 7.x renames line up.
- `tools/compare_libs.py <a> <b>` compares two decodings.
- `tools/check_addon.py <recording> [pace]` replays a recording through the
  add-on's real connection thread (`feed.recorded_frames`, pauses scaled by
  pace; 1 keeps the timing the one- and ten-second rules depend on) and
  compares its files with what happened, counted once per message id. Output
  in `artifacts/checks/`. Guest requests have no independent count yet: the
  link layer carries applicant queues, not single requests (F28).

7.0.1 for the comparison lives in `artifacts/lib-7.0.1` (wheels for cp313
win_amd64 from PyPI; `protobuf_to_dict.py` copied from the vendored lib).

Finding lives: the TikTok LIVE gaming feed works without signing in. Mute the
page at once (autoplay with sound).

## Still to build
- Windows Sandbox with portable NVDA 2026.1.1, 2026.2, 2026.3beta4 and the
  add-on installed, silent synthesizer, speech read from NVDA's log, the
  vendored TikTokLive swapped for a replaying one. Pattern: BST Radio's
  `Windows/sandbox` (persistent sandbox, request file, heartbeat, minimized
  without focus, muted).
