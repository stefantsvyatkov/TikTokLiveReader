# Version 2.0

Stabilization and restructuring, agreed 2026-10-13. No new user-facing
strings; behaviour changes only where a finding is proven by a test or by a
live recording.

## Decisions

- Minimum NVDA 2026.1 (Python 3.13, 64-bit only); `lastTestedNVDAVersion`
  2026.3 once tested on it. 2026.3 keeps `BACK_COMPAT_TO = 2026.1` and has no
  breaking add-on API changes.
- Settings stay in the separate `tiktokLiveReader.ini` in NVDA's config
  folder (not `config.conf`: changes would go into whichever profile is
  active; `registerSection(isBaseOnly=True)` only exists from 2026.3).
- The settings dialog stays the user's own; it is stabilized, not replaced.
- Code style follows the NVDA add-on template (tabs, ruff, line length 110),
  applied in one commit of its own.
- TikTokLive 6.6.5 vs 7.0.1 is decided on data: both decode the same recorded
  raw messages. 7.x needs pydantic-core (compiled; one cp313 win_amd64 build
  suffices with the 2026.1 minimum) and is AGPL-3.0 with an integration
  exception.
- Live tests never use the user's own live: busy public lives are recorded
  raw, controlled cases are real recorded messages with one field changed,
  and the live page's chat is a second, library-independent source.

## Phases

1. Safety net - [x] tests that pin 1.8's event pipeline; [x] tests for the
   scripts, navigation, positions, archive and settings file; [x] raw live
   recorder and replay; [x] library comparison (no decoding difference for the
   add-on; recommendation: stay on 6.6.5, isolate the library in one module);
   [x] Windows Sandbox with NVDA 2026.1.1, 2026.2 and 2026.3beta4 running the
   add-on; [x] CI workflow (runs once pushed); [ ] replay of the three live
   recordings through 1.8.
2. Module split behind the tests, behaviour unchanged.
3. Fixes from `findings.md`, each with a test or recording.
4. Stress test in the sandbox on all three NVDA versions, live comparison
   loop.
5. Version 2.0, minimum 2026.1, changelog draft for the user.
