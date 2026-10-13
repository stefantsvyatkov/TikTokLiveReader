# Findings in 1.8

IDs are referenced by `tests/test_known_issues.py`. "Pinned" means a test
holds today's behaviour; "live" means it is only fixed once a recording
confirms it.

## Connection

- F1 Pinned. `disconnect()` calls `client.stop()`, which does not exist; the error is
  swallowed and the websocket stays open until the stream ends.
- F2 Pinned. A connection left open by F1 shares `_should_run` with the next one: when
  its stream ends it reports "live ended" into the new session.
- F27 Pinned. Because of F1, `disconnect()` waits its full 3 s join for the
  connection thread. Scripts run on NVDA's main thread, so switching the
  add-on off while connected freezes NVDA for 3 s; so do closing NVDA and
  changing the user name in the settings during a session.
- F3 `ui.message` and gesture rebinding (`_unbind_nav` in the failure and
  live-end callbacks) run on the connection thread instead of NVDA's main
  thread.
- F15 `_client_loop` is never the loop the client runs on (see library.md);
  each connection also leaves two event loops unclosed (ResourceWarning in the
  tests).
- F16 `DiggEvent` is imported unconditionally; TikTokLive 6.6.6+ has no such
  class, so updating the library would break connecting.
- F23 After a quick off/on, the old stats thread can keep running beside the
  new one (`_stop_event` is cleared again before it notices).

## Events

- F4 Pinned. `_is_processed` looks for `msgId`, `id` and
  `base_message.msg_id`; the field is `base_message.message_id`, so
  deduplication by message id never happens and only the text checks below
  catch duplicates.
- F5 Pinned. The same comment from the same person is dropped for the rest
  of the session.
- F6 Pinned. `events.txt` drops a line identical to an earlier one (a second
  share, the same like count again), while the per-type file keeps it.
- F7 Pinned, live. A gift that cannot streak (`type != 1`) is dropped when
  `repeat_end` is 0; the library treats only streakable gifts as streaking.
  Needs recordings of real non-streakable gifts.
- F8 Pinned. The same gift with the same count from the same person within a
  second is logged once.
- F9 Pinned. A new line inside a comment splits the entry into two lines.
- F10 Pinned. A name that cleaning reduces to nothing gives entries such as
  ": hey" and an empty follower line (counted, but not reachable by
  navigation).
- F11 Pinned. Likes still being summed (10 s timer per person) are dropped
  when the session ends: `like_manager.stop()` cancels the timers.
- F12 Pinned. The top gifters and top likes files are written every 10 s but
  not at the end; a short session leaves them empty, an archive copies them
  stale.
- F13 The add-on listens to `SocialEvent` and to the derived
  `FollowEvent`/`ShareEvent`, so each follow and share is handled twice; the
  follower set and the one-second share check hide it.
- F25 Live. Guest requests carrying only `user_id` (LinkMicMethod) are not
  resolved to a name; real requests may use other message shapes. Needs
  recordings.
- F26 `LikeEvent` and `DiggEvent` both feed the like counter in 6.6.5;
  whether TikTok sends both for the same taps needs recordings. The user has
  tuned likes by hand: change only with evidence.

## NVDA integration

- F17 Sounds use `winsound` (Windows default device, not NVDA's output
  device) and scale volume in a Python loop over every sample.
- F18 Importing the add-on at NVDA start imports TikTokLive and its
  dependencies, reads the settings and starts the sound thread, even when the
  add-on is never used.
- F19 Speech goes through `speechbuffer.json`, polled every 0.5 s, although
  writer and reader are in the same process.
- F20 Settings live in three places kept in sync by hand: the ini file,
  `GlobalPlugin` attributes and `client` module globals.
- F21 Exceptions are swallowed without logging, so failures cannot be
  diagnosed from NVDA's log.
- F22 Clearing files (main thread) races with handlers writing (connection
  thread); there is no lock.
- F24 Script categories differ (literal, translated, none), so the scripts
  are scattered in Input gestures. Dead code: `SpeechManager.speak`,
  `_watcherThread`, `audioop`, `setup()`, the winsound constant shims, the
  inactive branch of `script_reportViewers`.

## Not issues

- Double spaces inside a comment do not break the time stamp split: it splits
  from the right.
