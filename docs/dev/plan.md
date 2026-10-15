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

## New features for 2.0 (agreed 2026-10-15, plan only)

Chosen by the user from the list of everything the library can do
(`artifacts/library-features.txt`, not in Git); they go into 2.0, whose
version and user documentation wait until then (the documentation is the
user's: the new tab, the command, the stats lines, reposts, the fan club and
pause lines). Every text below is a new msgid unless marked; the Bulgarian is
the user's wording for the catalogue, which the user maintains.

1. Reposts (`SocialEvent` action 4, key
   `ttlive_repost_commentsArea_repostedUsername_im`; 50 in 14 of 34 recorded
   lives, dropped today). Same file and settings as shares (events, auto
   speak, sound); `shares.txt` lines say what happened, a share with the
   existing "{name} shared the live" / "{name} сподели лайфа" (until now the
   line was the name only).
   - "{name} reposted the live" / "{name} препостна лайфа"
2. New fan club member (`RoomEvent`, key `pm_mt_fan_live_joined_comment`,
   pieces: the user and the number; 12 in 5 lives): `events.txt` only, no
   speech, sound or setting.
   - "{name} became fan number {number} in the fan club" / "{name} стана фен
     номер {number} във фен клуба"
3. Pause and resume (`ControlEvent` STREAM_PAUSED with source "app_pause" /
   STREAM_UNPAUSED; TikTokLive's `LivePauseEvent` / `LiveUnpauseEvent`; in 7
   lives, some several times a minute): always spoken, as "The live has
   ended" is, and in `events.txt`, each one.
   - "The live is paused" / "Лайфът е на пауза"
   - "The live has resumed" / "Лайфът продължи"
4. Stats file, four lines after the five there, in their form. Duration is
   H:MM since the live started, from the room info's `create_time` fetched
   once on connecting (a TikTok request, not the sign server); the counts are
   the add-on's own (the room info's like, comment and share counts are 0 in
   the web API).
   - "Duration: {time}" / "Продължителност: {time}"
   - "Comments: {count}" / "Коментари: {count}"
   - "Shares: {count}" / "Споделяния: {count}" (reposts included)
   - "Gifts: {count}" / "Гифтове: {count}"
5. Recording the live. What is recorded is the stream TikTok sends viewers:
   the host's camera and microphone with the app's filters; comments and gift
   animations are drawn by each viewer's app and are not in it (to check:
   lives with guests may be the combined picture). Recording works only while
   the add-on is connected; it stops on switching off and when the live ends;
   after a reconnection a new file starts.
   - Settings tab, in this order:
     - tab "Live recordings" / "Запис на лайфове"
     - check box "&Start recording when connected" / "&Започване на запис при
       свързване" (off by default)
     - list "&Quality" / "&Качество": "Video (720p)" / "Видео (720p)"
       (default) and "Audio only" / "Само звук": all TikTok gives a viewer
       who is not logged in (see the trial below), so the original,
       1080p, 540p and 360p first planned do not exist
     - last, as the text files destination: "Recordings &folder" /
       "&Местоположение на записите", with the existing "&Browse..." /
       "&Преглед..." button and "Select recordings folder" / "Изберете
       местоположение на записите"; default Videos\TikTok live; files named
       as archives, "2026-10-15 20-30-05 host.mp4"
   - Command NVDA+shift+control+e, only while connected:
     - description "Start or stop recording the live" / "Започва или спира
       записа на лайфа"
     - "Recording started" / "Записът е стартиран"
     - "Recording stopped" / "Записът е спрян"
     - not connected: "Not connected to a live" / "Няма връзка с лайф"
     - "Could not start recording" / "Неуспешно започване на запис"
   - FFmpeg, asked for when the check box is set or the command is used and
     it is not installed: downloaded with a progress dialog (with Cancel) and
     installed into NVDA's configuration folder (kept across add-on updates).
     The build: GyanD/codexffmpeg's release 9.0.2 on GitHub,
     `ffmpeg-9.0.2-essentials_build.zip`, 114 768 076 bytes, SHA-256
     60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba (GitHub's
     digest; versioned releases stay, BtbN's dated builds are pruned); only
     `bin/ffmpeg.exe` (105 MB) and `LICENSE` are kept. It copies the stream
     into fragmented MP4 (`-c copy -movflags
     +frag_keyframe+empty_moov+default_base_moof`, so a file cut short still
     plays) in its own process; NVDA only starts and stops it.
     Trial on 2026-10-15 (one minute of a public phone live in each quality,
     the files deleted after): the room info's stream data offers only `hd`
     (720x1280, 1000 kbit/s for phone lives, 1800 for lives from a computer)
     and `ao` (audio only), with FLV, HLS and CMAF URLs; FFmpeg used 0.1 s of
     CPU in 30 s; the video file had H.264 at about 15 frames a second and 113
     kbit/s (a still picture), so at most about 0.5 GB an hour; audio only
     about 30 MB an hour. A frame showed no comments or gift animations; that
     live had guests and the picture was TikTok's grid of them. The audio is
     the broadcaster's, the same in both qualities: AAC, 48 kHz, stereo, 64
     kbit/s from the phone app (3 lives), 128 kbit/s from computers (2 lives).
     - "Recording needs FFmpeg, a free program of about {size} MB. Install it
       now?" / "За записа е нужна безплатната програма FFmpeg, около {size}
       MB. Да се инсталира ли сега?"
     - "Downloading FFmpeg" / "Изтегляне на FFmpeg"
     - "Downloaded {done} of {total} MB" / "Изтеглени {done} от {total} MB"
     - "FFmpeg is installed" / "FFmpeg е инсталиран"
     - "Could not install FFmpeg: {error}" / "Неуспешно инсталиране на FFmpeg:
       {error}"
   - Checks before it counts as done: record a few minutes of public phone
     lives in each quality and check them with ffprobe and a frame; a live
     with guests; NVDA's CPU and memory in the sandbox while recording; a
     recording cut off by switching off and by the live ending; the download,
     checksum and progress dialog in the sandbox on all three NVDA versions.

Dropped: gift restrictions (`WebcastGiftDynamicRestrictionMessage` is empty in
all 84 recorded, its field of length 0); the room title.
