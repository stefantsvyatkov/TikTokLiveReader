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
- (`test_known_issues.py` pinned 1.8's wrong behaviour, one test per
  finding; each fix moved its test, with the right expectation, to
  `test_pipeline.py` or `test_plugin.py`, and the file is gone.)
- `test_vendor.py` - `vendor.py` keeps the bundled libraries private (a small
  made-up lib in the temporary folder, and the add-on's own).

The suite takes about 25 s (70 s before F27 was fixed: a 3 s freeze in every
test that switched off a held session).

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
  add-on's real connection thread on recorded time (`feed.VirtualClock`; with
  a pace it waits the recorded pauses scaled by it instead) and compares its
  files with what happened, counted once per message id. Output in
  `artifacts/checks/`. Guest requests have no independent count yet: the
  link layer carries applicant queues, not single requests (F28).

- `tools/snapshot_addon.py <out.json> <recording> [...]` replays recordings
  on recorded time (`feed.VirtualClock`: pauses advance the clock the add-on's
  modules read, and its like timers, at once) and saves files, speech, sounds
  and counters. Deterministic, about two minutes for the three 2026-10-13
  lives: snapshots before and after a refactoring must be identical, and
  after a fix they show exactly what it changed (`artifacts/snapshots/`).
  `tools/compare_snapshots.py <before> <after>` lists what changed.
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
(`-Stop` closes it). Scenarios: `smoke` (switch on, navigate, viewers,
switch off; `smoke-bg` the same with NVDA in Bulgarian, hearing the add-on's
Bulgarian translations: the agent sets NVDA's language for scenarios ending in
`-bg`) and `settings` (every control of the General page by name, OK
saves, Cancel does not, a bad user name is refused, Learn sounds speaks, a
new user name while connected archives the old session and reconnects). Text
is typed as Unicode characters: the sandbox takes the host's keyboard layout
(Bulgarian), so key codes would type Cyrillic. The sandbox keeps the focus of
the previous run (the tray, after a settings run). NVDA 2026.1.1 logs an
error for every character typed that way (its language is None; fixed in
2026.2); the driver leaves that error out of "no errors in NVDA's log". Adapted from BST Radio's sandbox: one persistent sandbox,
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

### Other add-ons

`conflicts` installs `sandbox/probe` next to the add-on: a test add-on that,
as add-ons usually do, imports its own `pydantic`, `httpx`, `websockets` and
`anyio` at NVDA's start (its `lib/` on `sys.path` only for that) and keeps
NVDA's `certifi`, `idna`, `typing_extensions` and `attr`. NVDA+control+alt+
shift+k says who owns each name in `sys.modules` and whether code holding
those modules still works, including imports made only when used (a package
`__getattr__` importing a submodule, `from . import _client` in a function,
`idna.encode(..., uts46=True)`, `certifi.where()`). The scenario asks before,
during and after two lives in a row. `conflicts-store` also installs every
add-on in `artifacts\sandbox\extra-addons` (not in Git): real store add-ons
that bundle packages the add-on bundles too.

Of the 510 add-ons compatible with NVDA 2026.2 in the store (NVDA's cached
store list), only Document reader for NVDA 1.0 (Sujan Rai, 159 MB) bundles
any of them: `attr`/`attrs` 26.1.0, `certifi` 2026.5.20, `dateutil` 2.9.0,
`idna` 3.16, `six` 1.17.0, `typing_extensions` 4.15.0 and a `secrets.py`, the
same versions as ours or older. It puts its `libs` first on `sys.path` for
good and imports them at NVDA's start. Found by searching GitHub code under
`globalPlugins` for imports of the bundled packages and the store's source
URLs; the add-ons that use AI services mostly call the services with their
own small clients (AI-Hub) instead of bundling SDKs.

Runs on 2026-10-14, both scenarios on all three NVDA versions: during a live
the add-on decodes, NVDA's `certifi` and `idna` stay NVDA's and work, and the
probe's modules it holds work; its imports made only when used (`pydantic`,
`httpx` in the probe) get the add-on's modules, the known limit
(docs/dev/library.md, "Isolation"), which the scenario records but does not
fail. 0.3 s after switching off every name is back with its owner and works,
after each of two lives; nothing in NVDA's log. With Document reader
installed NVDA starts in 9-11 s instead of 5-6.5. The first run found NVDA's
own `idna` failing during a live, now fixed by sharing it; the sandbox's
replaying client now returns from `connect()` when disconnected, as the real
one does, so the add-on gives the modules back at once.

### Stress

`stress` replays a busy real live fast with every event written, spoken
(auto speak on) and sounded (the agent writes those settings): `-Recording
stress.jsonl -Pace 0.05`. `stress.jsonl` is the first 30 minutes of a live
recorded on 2026-10-14 (i.freshta1, 2967 messages: 1476 joins, 281 comments,
197 likes; real names, so only in `artifacts\sandbox\fixtures`), 20 times as
fast: about 33 messages a second, against 2 at most in the 37 recorded lives.
Every 4 s the driver presses NVDA+t and times the answer; then it reads the
last comment, switches off, checks that NVDA answers and that speech stops,
and notes the files and NVDA's memory (tasklist).

On 2026-10-14, all three NVDA versions: 22 of 22 answers in 0.13-0.14 s
during the live, the last comment in 0.19-0.20 s, NVDA answers 0.13 s after
switching off (0.72 s on 2026.1.1), no speech after it, nothing in the log,
NVDA's memory 152-158 MB before and 234-237 MB after (the library). The
replay waits the recorded pauses after handling each frame, so handling time
adds up: when switched off after 91 s it was at 75 s of its 90, about 6.4 ms
per message for decoding (1.4 ms of it on the host) and everything the add-on
does with it. `tools/check_addon.py` on the same fixture matches the
recording but for a comment's trailing space (the add-on trims it), a
sticker comment (F31) and one anonymous join ("someone").
