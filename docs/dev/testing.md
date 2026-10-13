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
- `test_vendor.py` - `vendor.py` keeps the bundled libraries private (a small
  made-up lib in the temporary folder, and the add-on's own).

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

- `tools/snapshot_addon.py <out.json> <recording> [...]` replays recordings
  on recorded time (`feed.VirtualClock`: pauses advance the clock the add-on's
  modules read, and its like timers, at once) and saves files, speech, sounds
  and counters. Deterministic, about two minutes for the three 2026-10-13
  lives: snapshots before and after a refactoring must be identical, and
  after a fix they show exactly what it changed (`artifacts/snapshots/`).
  Replayed in real time instead, the like timers write the speech buffer
  from their own threads beside the connection thread and corrupt it like
  F30.

- `tools/anonymize_recording.py <recording> <out> [method ...]` rewrites every
  name, handle, text and user id to stable stand-ins (the same person keeps
  the same stand-in, so deduplication and applicant queues behave as
  recorded) and re-encodes the payloads, so real message shapes can become
  committed fixtures.

7.0.1 for the comparison lives in `artifacts/lib-7.0.1` (wheels for cp313
win_amd64 from PyPI; `protobuf_to_dict.py` copied from the vendored lib).

Finding lives: the TikTok LIVE gaming feed works without signing in. Mute the
page at once (autoplay with sound).

## Windows Sandbox with real NVDA

`sandbox\Run-Sandbox.ps1 [-Scenario smoke] [-Nvda 2026.2,...] [-Recording smoke.jsonl] [-Pace 1]`
(`-Stop` closes it). Adapted from BST Radio's sandbox: one persistent sandbox,
started minimised without taking the focus; `artifacts\sandbox` is mapped
read-only as `C:\Stage`, `artifacts\sandbox-runs` writable as `C:\Runs`; the
agent writes a heartbeat and takes requests from `request.txt`. Changing
`SandboxAgent.ps1` needs `-Stop` first (the running agent keeps its old copy).

Per run the agent mutes every playback device of the sandbox (no run without
it: the sandbox's sound reaches the host), makes a portable NVDA of the
requested version once (`C:\NVDA\<version>`) and starts it with a fresh
configuration: silent synthesizer, no welcome or update dialogs, log level 12,
the staged add-on copied into the add-ons folder, and `tiktokLiveReader.ini`
(user "host", text files in the run's folder; written without a byte order
mark, F29). With a recording, the staged add-on's TikTokLive gets
`_sandbox_replay.py` (`sandbox/replay_client.py`) and exports its client when
`TIKTOK_REPLAY` is set; the repository's add-on is never changed.
`sandbox/driver.py` (portable Python 3.13 inside) presses real keys with
SendInput, reads speech from NVDA's log and writes `results.txt`.

`tools/make_fixtures.py` writes the synthetic recordings to
`artifacts\sandbox\fixtures`.

Smoke scenario on 2026-10-13: 1.8 passes on 2026.1.1, 2026.2 and
2026.3beta4; NVDA needs 2.85-2.90 s to answer the next key after switching the
add-on off (F27).
