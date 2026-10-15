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
   add-on; [x] CI workflow (passes on GitHub); [x] replay of the three live
   recordings through 1.8 (F5, F7, F30-F33 confirmed or found).
   Decided afterwards: upgrade to TikTokLive 7.0.1 in 2.0, after the adapter
   (6.6.5 signs through the old `tiktok.eulerstream.com`); license 2.0 as GPL
   v2 or later, applied at release once the code written by the contributor
   Muhammad (vendor_loader.py, parts of client.py) is rewritten - his
   Indonesian translation stays; conflict tests with test add-ons and real
   store add-ons (list them for the user before downloading).
   License wording to apply at the 2.0 release (approved): README line
   "Distributed under the **GNU General Public License, version 2 or
   later**." plus "The bundled TikTokLive library and its dependencies keep
   their own licenses (TikTokLive: AGPL-3.0 with additional permissions); their
   license files are included in the add-on."; buildVars `addon_license`
   "GNU General Public License v2.0 or later"; doc/en and doc/id "It is
   distributed under the GNU General Public License, version 2 or later.";
   doc/bg "Разпространява се под лиценз GNU General Public License, версия 2
   или по-късна." Show the user the exact diff when applying.
2. Module split behind the tests, behaviour unchanged. After each step the
   suite and the sandbox smoke run, then commit and push.
   - [x] 1 `settings.py`, `i18n.py`
   - [x] 2 `store.py` (the place for the F22/F30 lock and tolerant reads)
   - [x] 3 `announcer.py` (F17, F19 are fixed there)
   - [x] 4 `likes.py` (`flush_pending` is the F11 fix)
   - [x] 5 `tiktok_adapter.py`, `events.py`, `pipeline.py`; snapshots of the
     three 2026-10-13 lives identical before and after
   - [x] 6 `session.py` (was `client.py`), `vendor.py` written anew in place
     of `vendor_loader.py`. Muhammad's code is gone: `vendor_loader.py`
     (replaced), and from his client.py changes `_identity`/`_cached_translate`
     (step 1), the speech callbacks and sample clamping (steps 3, 6), the
     comment text extraction (rewritten in `tiktok_adapter._comment_text` and
     `pipeline._display_name`), the vendor runtime calls; the listener
     registrations are written anew in `tiktok_adapter.new_client`. Left: his
     four lines keeping auto speak on when switching on
     (`script_toggleActive`), rewritten in step 7. His Indonesian translation
     stays (user's decision).
   - [x] 7 `dialogs.py` (the dialog as `SettingsDialog`, controls created in
     the same order, so the same Tab order), `positions.py`; his four lines
     are now `_follow_auto_speak`. Checked by the sandbox's `settings`
     scenario before and after, on all three NVDA versions.
   - [x] 8 NVDA formatting with ruff 0.14.5 (same syntax tree before and
     after for every file)
   Phase 4 also runs the smoke with NVDA in Bulgarian (translations come
   through `i18n.py` since step 1).
3. Fixes from `findings.md`, each with a test or recording.
   - [x] F4 with F5, F6, F8, F13, F32, F33: duplicates by message id
   - [x] F7: gifts that cannot streak
   - [x] F9, F10: one line per entry, a name for every entry
   - [x] F11, F12: pending likes and top lists written at the end
   - [x] F19, F22, F29, F30: speech queue, file lock, tolerant reads, BOM
   - [x] F1, F2, F3, F15, F23, F27: the connection stops at once and alone
   - [x] F35: the settings dialog comes to the front
   - [x] F17: sounds on NVDA's output device
   - [x] F24: one script category
   - [x] F18: nothing loaded or started before the add-on is used
   - [x] F21: failures logged
   - [x] F28: the newcomer in the applicant queue (F25 waits for data)
   - [x] TikTokLive 7.0.1: snapshots of the three lives the same as on 6.6.5
     but for one anonymous join ("someone" instead of an empty name)
4. Stress test in the sandbox on all three NVDA versions, live comparison
   loop.
   - [x] other add-ons: probe add-on and Document reader (`conflicts`,
     `conflicts-store`); NVDA's `certifi` and `idna` shared
   - [x] `stress`: a busy live 20 times as fast, auto speak and sounds on
   - [x] smoke with NVDA in Bulgarian (`smoke-bg`, all three versions; the
     catalogues match their .mo files and have every string the code
     translates but the script category, the add-on's name, as in 1.8)
   - [x] live comparison on 7.0.1: the 2026-10-14 recordings found the link
     layer decode error, F36 and F37; five lives then matched
     (docs/dev/testing.md)
5. Version 2.0, minimum 2026.1, changelog draft for the user.

## New features (agreed 2026-10-15, plan only)

Chosen by the user from the list of everything the library can do
(`artifacts/library-features.txt`, not in Git). Every new text is a new
msgid for the user to translate; the English below is a proposal.

1. Reposts (`SocialEvent` action 4, key
   `ttlive_repost_commentsArea_repostedUsername_im`; 50 in 14 of 34 recorded
   lives, dropped today). Same file and settings as shares; `shares.txt`
   lines then say what happened: "{name} reposted the live" (new) and
   "{name} shared the live" (the existing msgid, so share lines gain the
   verb). Spoken and in `events.txt` as shares are.
2. New fan club member (`RoomEvent`, key `pm_mt_fan_live_joined_comment`,
   pieces: the user and the number; 12 in 5 lives): `events.txt` only, no
   speech, sound or setting. "{name} became fan number {number} in the fan
   club".
3. Pause and resume (`ControlEvent` STREAM_PAUSED with source "app_pause" /
   STREAM_UNPAUSED; TikTokLive's `LivePauseEvent` / `LiveUnpauseEvent`; in 7
   lives, some several times a minute): always spoken, like "The live has
   ended", and in `events.txt`. "The live is paused", "The live has resumed".
4. Stats file, short lines ending in a colon as the five there: "Duration:
   {time}" (H:MM since the live started, from the room info's `create_time`,
   fetched once on connecting: a TikTok request, not the sign server),
   "Comments: {count}", "Shares: {count}" (reposts included), "Gifts:
   {count}", from the add-on's own counts. The room info's like, comment and
   share counts are 0 in the web API.
5. Recording the live: the stream TikTok sends viewers, that is the host's
   camera and microphone with the app's filters; comments and gift
   animations are drawn by each viewer's app and are not in it (to check:
   lives with guests may be the combined picture). Through FFmpeg: when the
   option is switched on the add-on asks to download it and installs it with
   a progress dialog, into NVDA's configuration folder (kept across add-on
   updates); a pinned build (BtbN's LGPL win64 9.0 is about 73 MB, gyan.dev's
   9.0.2 essentials about 110 MB), its SHA-256 checked before use. FFmpeg
   copies the stream into fragmented MP4 (`-c copy`, so a file cut short still
   plays) in its own process; NVDA only starts and stops it. Default quality
   Original; others from the stream data (seen: hd 720p at 1.8 Mbit/s, about
   0.9 GB an hour, and `ao`, audio only). The stream URLs come from the room
   info. Texts: the setting, the quality choices, the download question and
   progress, errors.
   Checks before it counts as done: record a few minutes of public phone lives
   in each quality and check them with ffprobe and a frame; a live with
   guests; NVDA's CPU and memory in the sandbox while recording; a recording
   cut off by switching off and by the live ending; the download, checksum and
   progress dialog in the sandbox on all three NVDA versions.

Dropped: gift restrictions (`WebcastGiftDynamicRestrictionMessage` is empty in
all 84 recorded, its field of length 0); the room title.
