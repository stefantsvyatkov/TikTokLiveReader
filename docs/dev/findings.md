# Findings in 1.8

IDs are referenced by `tests/test_known_issues.py`. "Pinned" means a test
holds today's behaviour; "live" means it is only fixed once a recording
confirms it.

## Connection

Fixed in phase 3 (2026-10-13): F1, F2, F27, F15, F23, F3. The adapter runs the
client on an event loop of its own (`tiktok_adapter.Connection`) and stops it
by disconnecting and cancelling on that loop, without waiting; each switch-on
is a run (`session._Run`) whose events and reports are dropped once it ended;
one stats thread per run; the plugin's connection callbacks and the speech
reader speak through `wx.CallAfter`, and a report of a session switched off
since is dropped. Measured in the sandbox on all three NVDA versions: NVDA
answers 0.13 s after switching off (was 2.85-2.90 s). The tests run in 25 s
instead of 85 and leave no event loop unclosed.

- F1 Pinned. `disconnect()` calls `client.stop()`, which does not exist; the error is
  swallowed and the websocket stays open until the stream ends.
- F2 Pinned. A connection left open by F1 shares `_should_run` with the next one: when
  its stream ends it reports "live ended" into the new session.
- F27 Pinned. Because of F1, `disconnect()` waits its full 3 s join for the
  connection thread. Scripts run on NVDA's main thread, so switching the
  add-on off while connected freezes NVDA for 3 s; so do closing NVDA and
  changing the user name in the settings during a session. Measured in real
  NVDA 2026.1.1, 2026.2 and 2026.3beta4: the next key is answered 2.85-2.90 s
  later.
- F3 `ui.message` and gesture rebinding (`_unbind_nav` in the failure and
  live-end callbacks) run on the connection thread instead of NVDA's main
  thread.
- F15 `_client_loop` is never the loop the client runs on (see library.md);
  each connection also leaves two event loops unclosed (ResourceWarning in the
  tests).
- F16 `DiggEvent` is imported unconditionally; TikTokLive 6.6.6+ has no such
  class, so updating the library would break connecting. Fixed: only
  `tiktok_adapter.event_classes()` imports event classes, `DiggEvent` as an
  optional one; the add-on runs on TikTokLive 7.0.1.
- F23 After a quick off/on, the old stats thread can keep running beside the
  new one (`_stop_event` is cleared again before it notices).

## Events

Fixed in phase 3 (2026-10-13): F4, F5, F6, F8, F13, F32, F33. Every event
carries TikTok's message id and `pipeline.handle` handles each (kind, id) once;
the text and one-second rules are gone, a person still counts once as a
follower and as a visitor. With kept text files, comment and event lines of
earlier sessions are not logged again (the history sent on connecting); a
comment identical to one in those files is skipped, the one case left of F5.
`tools/check_addon.py` on the three 2026-10-13 lives, before -> after: comments
78 -> 102 of 102, 92 -> 96 of 97 (the one left is a sticker, F31) and 43 -> 45
of 45; shares 58 -> 71 of 71; the like sums that were off by a repeated message
are right.

- F4 Pinned. `_is_processed` looks for `msgId`, `id` and
  `base_message.msg_id`; the field is `base_message.message_id`, so
  deduplication by message id never happens and only the text checks below
  catch duplicates.
- F5 Pinned. The same comment from the same person is dropped for the rest
  of the session. The text check does catch something real: TikTok sends the
  history (messages from before connecting) twice, in the first frame and a
  few frames later, with the same message ids (recorded 2026-10-13). The fix is
  F4, deduplicating by message id, not dropping the check. Confirmed live with
  `tools/check_addon.py`: on a Bulgarian live 24 of 102 comments were lost
  (people repeating an unanswered question: one asked "кой град си" 7 times),
  3 of 97 and 2 of 45 on two other lives.
- F6 Pinned. `events.txt` drops a line identical to an earlier one (a second
  share, the same like count again), while the per-type file keeps it.
- F7 Fixed in phase 3: a gift is skipped only while the library says it is
  streaking (`GiftEvent.streaking`, false for gifts that cannot streak); the
  live check finds 18 of 18 gifts (was 17). Before: A gift that cannot streak (`type != 1`) is
  dropped when `repeat_end` is 0; the library treats only streakable gifts as
  streaking. Recorded 2026-10-13: of 73 gifts, the one that cannot streak
  ("Heart Me") came with `repeat_end` 0, so 1.8 lost it.
- F8 Pinned. The same gift with the same count from the same person within a
  second is logged once.
- F9 Fixed in phase 3: line breaks in a comment become spaces. Before: a new
  line inside a comment split the entry into two lines.
- F37 Fixed on 2026-10-14, as F9 for names: line breaks (including U+2028 and
  U+2029) in a name become spaces, cleaned or not (`_sanitize_name`); nothing
  else in raw names changes. Before: a visitor whose name had a U+2028 in it,
  on a live recorded that day, was one line for the add-on (it splits on
  newlines only) but two in Notepad and in `check_addon` (`splitlines`).
- F10 Fixed in phase 3: with names cleaned, a name cleaning would leave
  without a letter or digit becomes the person's handle (or stays as it is);
  names not cleaned stay exactly as they are. Before: entries such as ": hey"
  and empty follower lines. With names cleaned this was every name in Arabic,
  Thai, Vietnamese... script: on islam8qurann's live their visitors merged into
  one empty visitor (1679 instead of 1916) and their likes were dropped (158
  lines instead of 204); a name cleaned to "[] ." looked non-empty.
- F11 Fixed in phase 3: `session.disconnect` reports the pending sums. Before:
  likes still being summed (10 s timer per person) are dropped
  when the session ends: `like_manager.stop()` cancels the timers.
- F12 Fixed in phase 3: `session.disconnect` writes the top files before the
  plugin archives. Before: the top gifters and top likes files were written
  every 10 s but not at the end; a short session leaves them empty, an archive copies them
  stale.
- F13 The add-on listens to `SocialEvent` and to the derived
  `FollowEvent`/`ShareEvent`, so each follow and share is handled twice; the
  follower set and the one-second share check hide it.
- F38 Fixed on 2026-10-14: guest requests from people the add-on had not seen
  yet (no comment, join or like before) were dropped: the link layer lists
  the applicant queue by user id only. TikTokLive 7's `LinkEvent`
  (WebcastLinkMessage) lists the same queue with full users; in the 15 lives
  with applicants recorded by then its applicants were exactly the link
  layer's, named before or with the link layer change for 58 of 63 newcomers
  and at most 0.86 s after it for the other 5. The add-on now learns the
  names from it (`events.LinkMessage.named`) and waits up to `NAME_WAIT` (5 s)
  for a newcomer's name; `LinkEvent` is never a request itself and does not
  touch the queue. Requests against applications (`check_addon`): 33 of 50
  before, 45 of 50 after (errdhigogoli 15 to 16 of 17, saligullu0740 15 to 22
  of 25, islam8qurann 3 to 7 of 8, princearif710 5 of 5): now every newcomer
  in the queue, the rest being the queue found on connecting (people who
  applied before) and type 2 changes that brought nobody new. The user
  guide's limitation
  on requests from people without activity no longer holds.
- F25 Live. Guest requests carrying only `user_id` (LinkMicMethod) are not
  resolved to a name; real requests may use other message shapes. Needs
  recordings: all 277 LinkMicMethod messages recorded by 2026-10-13 are
  m_type 8 (fan tickets), which the add-on skips.
- F30 Fixed in phase 3: `store.py` writes and clears under one lock and reads
  with damaged characters replaced; the speech buffer is gone (F19). Before: Text files are appended from several threads (the
  connection thread, one like timer per person) without a lock; Windows emulates
  append as seek-to-end plus write, so two lines written at the same moment
  overwrite each other. Replaying a busy live left a like line cut in half,
  starting in the middle of an emoji. Navigation reads the files as strict
  UTF-8 and only catches OSError, so after such a line the file can no longer
  be browsed and NVDA stays silent on it for the rest of the session.
- F31 Live. A comment that is only a sticker or emote has empty text and is
  dropped. Kept as it is (user's decision, 2026-10-13): announcing it would need
  a new string.
- F32 Live. A second share by the same person within a second is dropped (the
  rule hides F13's double handling): one viewer sharing every 0.8 s lost 9 of
  10 shares.
- F33 Live. Besides the history, about 0.3-0.6 % of live messages arrive twice
  with the same id (joins, likes, gifts restrictions, viewer counts). Likes have
  no duplicate check at all, so a repeated like message is counted twice per
  person (and in top likes). Deduplicating every event by message id (F4)
  covers F5, F6, F8, F32 and F33 at once.
- F28 Fixed in phase 3: on a list change the applicants not in the previous
  queue are announced, by the name the add-on has seen for their id; nobody at
  the first queue. On islam8qurann's live (19 list changes, a queue of about 25)
  it finds the 7 newcomers and names those it knows (3 or 4, depending on what
  it saw before); 1.8 announced 8 requests, mostly of people who had applied
  long before, two of them twice. Before: A `LinkLayerEvent` list change carries the whole
  applicant queue (`list_content.user_list.applied_list`, user ids only) and the
  guests already linked. The add-on announces the first applicant whose name it
  has seen before, so on a busy live it names someone who applied earlier, not
  the newcomer; the new applicant is the id missing from the previous list.
  With one applicant the result is right, which is why it looked fine.

## NVDA integration

- F17 Fixed in phase 3: sounds play through `nvwave.WavePlayer` on the output
  device chosen in NVDA, at the add-on's volume (`setVolume`); the sandbox's
  settings scenario checks that a sound plays to its end. Before: sounds used
  `winsound` (Windows default device, not NVDA's output
  device) and scale volume in a Python loop over every sample.
- F18 Fixed in phase 3: the bundled library loads on the first switch-on, in
  the connection thread (`tiktok_adapter.runtime()`), the sound worker starts
  with the first session or the settings dialog; a test starts the plugin in a
  fresh interpreter and finds neither. Loading took 0.7 s on a fast machine;
  NVDA started in the sandbox in 4.5 s instead of 5.0-5.5. Before: importing
  the add-on at NVDA start imports TikTokLive and its
  dependencies, reads the settings and starts the sound thread, even when the
  add-on is never used.
- F19 Fixed in phase 3: texts for speech go through an in-memory queue to the
  speech reader, only while it runs. Before: speech went through
  `speechbuffer.json`, polled every 0.5 s, although writer and reader are in
  the same process; replaying a busy live in real time corrupted it (F30).
- F29 Fixed in phase 3: the settings file is read as `utf-8-sig`. Before: it
  was read as plain UTF-8: saved with a byte order
  mark (old Notepad, PowerShell 5's `-Encoding UTF8`), the first section header
  is not recognised, reading fails and every setting silently falls back to
  its default. Found by the sandbox, whose agent first wrote the file that way.
- F35 Fixed in phase 3: `gui.mainFrame.prePopup()`/`postPopup()` around the
  dialog; in the sandbox it now opens on the first press on all three NVDA
  versions. Before: the settings dialog was shown with `ShowModal()` alone, without
  `gui.mainFrame.prePopup()`/`postPopup()`. With portable NVDA (no UIAccess)
  Windows kept the first dialog behind the focused window ("Foreground took
  too long to change" in NVDA's log): nothing was spoken, keys went to the
  window behind, and since `_settingsDialog` was set, switching the add-on on
  was refused until the dialog was raised by pressing the shortcut again and
  then another key. NVDA's own dialogs (prePopup) came up at once. Installed
  NVDA may hide it; the fix is NVDA's way of showing a dialog.
- F20 Fixed in phase 2 step 1. Settings lived in three places kept in sync by
  hand: the ini file, `GlobalPlugin` attributes and `client` module globals.
  Now one `settings.Settings` owned by the plugin and handed to
  `client.apply_settings`; `connect()` still re-reads the file, as 1.8 did.
  The ini file is byte for byte what 1.8 wrote (compared for a missing, a
  partial and an odd file).
- F21 Fixed in phase 3: `logHandler.log` everywhere an exception was
  swallowed; a bug in handling an event is logged as an error with its
  traceback (`session` around `pipeline.handle`), expected failures (offline,
  a file that cannot be written, the signing server's limit) at debug-warning
  level. `feed.run_session` fails a test when the add-on logged an error, so
  the snapshots of the three lives also check that none is logged. Before:
  exceptions were swallowed without logging, so failures could not be
  diagnosed from NVDA's log.
- F22 Fixed in phase 3 with F30's lock. Before: clearing files (main thread)
  raced with handlers writing (connection thread).
- F24 Fixed in phase 3: one `scriptCategory = _("TikTok Live Reader")` for the
  plugin (an existing string), `_watcherThread` gone. Before: script categories
  differed (literal, translated, none), so the scripts
  are scattered in Input gestures. Dead code: `_watcherThread`, the inactive
  branch of `script_reportViewers` (`SpeechManager.speak`, `audioop` and the
  winsound constant shims went with phase 2 step 3, the shims also patched
  the shared `winsound` module, which has no `SND_SYNC`; `setup()` and
  `client.py`'s `__main__` block with step 5).
- F36 Fixed on 2026-10-14: TikTokLive's log (the client sets it to ERROR)
  reaches NVDA's as warnings ("TikTokLive: ..."), through
  `tiktok_adapter._LibraryLog`. Before: its own handler wrote to stderr, which
  NVDA logs as ERROR (`logHandler.redirectStdout`), with the error sound in
  NVDA's test builds. In 1.8 and 6.6.5 the same; on 7.0.1 a message that fails
  to decode is such an error (the type 18 link layer message before
  `_build_message_classes`). In 19 + 18 recorded lives no other library wrote
  to stderr.

## Not issues

- F26 (likes counted twice through `LikeEvent` and `DiggEvent`): 1088 like
  messages recorded on 2026-10-13, no `WebcastDiggMessage` at all.
- Double spaces inside a comment do not break the time stamp split: it splits
  from the right.
