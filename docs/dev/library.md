# TikTokLive notes

Bundled version 7.0.1 since 2026-10-13 (Modified AGPL-3.0: section 18 allows
integrating it into non-SaaS software; TikTokLiveProto AGPL-3.0-only with the
same sections; EulerApiSdk MIT), before that 6.6.5 (MIT), which signs through
the old `tiktok.eulerstream.com`.

`lib/` is built by `tools/build_lib.py` from the pinned wheels of
`tools/lib-requirements.txt` (CPython 3.13 win_amd64, no `bin/`, no byte code;
`protobuf3-to-dict` left out: no wheel, nothing imports it; licence texts the
wheels lack from `tools/lib-licenses/`; `secrets.py` and `zoneinfo` kept).
16.4 MB against 18 for 6.6.5. Loading takes 1.4 s with byte code cached (0.7 s for 6.6.5), about
6 s the first time, when Python compiles it, then 0.7 s to build the message
classes (below); since F18 that is on the first switch-on, in the connection
thread.

TikTokLive 7 differences the add-on meets, besides the renames below:
`add_listener` takes event classes only (1.8 also listened by name);
`_parse_webcast_response` needs `_room_id` set (the replay clients set it);
events have no `.type`, emit with `get_type()`; `connect()` answers a cancel by
running its loop again (`_clean_tasks`), which fails inside a running loop, so
`Connection.stop` disconnects first and cancels only a task still connecting;
`close()` does the same after closing the HTTP client, so `_close_loop` calls
`client.web.close()`, all that 6.6.5's `close()` did;
a missing user is None where 6.6.5 gave an empty one (an anonymous join reads
"someone" instead of an empty name). The adapter reads both versions.

TikTokLiveProto declares its message classes as pydantic dataclasses whose
types name modules imported at the end of each file (`"data.HashtagNamespace"`),
so pydantic leaves 420 of the 670 to be built on first use. It then resolves
the names with the caller's locals over the module's: the caller is
betterproto2's `parse(cls, data)`, whose `data` (the bytes) hides the module
`data`. The client builds the outer event class in a safe frame
(`event_type().parse(...)`), so it bites when a nested class is built first
inside `parse`: a `WebcastLinkLayerMessage` of type 18 (group change) failed
on a live recorded on 2026-10-14 ("'bytes' object has no attribute
'HashtagNamespace'", logged by TikTokLive and dropped); the type 11 ones (the
guest queue, F28) decoded, and the three reference lives have no type 18.
`tiktok_adapter.runtime()` builds all of them right after loading, with only
their own modules' names; `test_vendor` decodes a link layer message with
`LinkLayerEvent.parse` in a fresh process, which fails the same way without
it.

NVDA's Python is a py2exe build with only the standard library modules NVDA
uses (`library.zip`). pydantic, new in 7.x, imports `zoneinfo`, which no NVDA
2026 ships, so the first sandbox run of 7.0.1 failed to load the library; the
tests run on full Python and passed. Checked against each version's
`library.zip` (extracted from the installers with 7-Zip), `zoneinfo` is the
only module the library needs that is missing: `lib/zoneinfo` is CPython
3.13.13's (four files from the v3.13.13 tag, with Python's licence), its C part
`_zoneinfo` is missing too and it uses its pure-Python one. `secrets`, imported
by websockets and pydantic, is missing in 2026.1.1 only; `lib/secrets.py`, a
hand-written stand-in from 1.0, covers it. `test_vendor` hides both modules to
reproduce NVDA.

## Event flow

The websocket yields `ProtoMessageFetchResult` frames. Each message has
`method`, raw `payload` bytes, `msg_id` and `is_history` (backlog sent on
connect). `EVENT_MAPPINGS[method]().parse(payload)` makes the event;
`handle_custom_event` derives `FollowEvent`/`ShareEvent` from a
`SocialEvent` whose `base_message.display_text.key` contains "follow" or
"share", and `LiveEndEvent` from a `ControlEvent` with action ENDED or
SUSPENDED (the library then disconnects itself, so `run()` returns cleanly).
`WebsocketResponseEvent` is emitted for every message.

The message id is `event.base_message.message_id`.

## Decoding depends on class order

betterproto caches field metadata in `cls._betterproto_meta` and reads it
through normal attribute lookup, so a subclass silently uses its parent's
cached metadata when the parent was used first:

- `WebsocketResponseEvent()` raises `NameError` (an annotation of
  `ProtoMessageFetchResult` cannot be resolved in the events module) unless a
  `ProtoMessageFetchResult` was decoded first. The websocket loop always does
  that, so it never shows in practice.
- `GiftEvent` declares `from_user: ExtendedUser` and `m_gift: ExtendedGift`.
  If a bare `WebcastGiftMessage` was created before the first `GiftEvent`,
  decoded gifts get plain `User`/`Gift` without `nickname`/`streakable`.
  Live decoding never creates the bare classes.

Tests therefore encode with the event classes and decode whole frames
(`tests/feed.py`). Type hints are resolved through `sys.modules`, which holds
the vendored modules only inside `vendor.scope` (`tiktok_adapter.library_scope()`).

## Isolation

`vendor.py` (phase 2 step 6, replacing `vendor_loader.py`) makes every
top-level name in `lib/` private, read from the folder: 1.8's hand-written
list left `idna`, `certifi`, `h11`, `dateutil`, `six`, `mashumaro` and `ffmpy`
in `sys.modules` for NVDA and every add-on after the first connection, and
missed anything a library update adds (7.0.1 brings `attrs`, `pydantic`,
`pydantic_core`, `annotated_types`, `typing_inspection`). Copies of standard
library modules (`lib/secrets.py`, `lib/zoneinfo`) are not private: `load`
imports each first, Python's own if it has one, so with lib/ first on
`sys.path` a copy never hides the real module. Scopes are counted, so
two overlapping connections (F1/F2) no longer take the modules away from each
other: 1.8 restored a snapshot per scope, and the first to end removed them
while the other was still decoding. While a connection runs, the bundled
modules are what NVDA and other add-ons get if they import one of those names
for the first time; their already imported copies are untouched and put back
when the last scope ends.

## Loops

`TikTokLiveClient._asyncio_loop` returns a new event loop whenever none is
running; `run()` runs `connect()` on such a fresh loop. A loop obtained
outside `run()` is never the loop the client runs on. Stopping a running
client means awaiting `client.disconnect()` on its own running loop. There is
no `stop()` method.

## Gifts

`GiftEvent.streaking` is `gift.streakable and not repeat_end`;
`gift.streakable` is `gift.type == 1`.

## 6.6.5 to 7.x

Removed event classes the add-on imports: `DiggEvent` (imported
unconditionally, so connecting would fail), `CommentsEvent`,
`ScreenChatEvent`, `GuestInviteEvent`. New dependencies: `betterproto2`,
`TikTokLiveProto` (needs `pydantic`, hence the compiled `pydantic-core`),
`EulerApiSdk`. The client API the add-on uses is unchanged.

7.x renames fields the add-on reads: `base_message` -> `common`
(`message_id` -> `msg_id`), `CommentEvent.user_info` -> `user`,
`GiftEvent.from_user`/`m_gift` -> `user`/`gift` (the 6.6.5 properties `user`
and `gift` keep the code working), `RoomUserSeqEvent.m_total` -> `total` (the
add-on would report 0 viewers), `JoinEvent.count` -> `member_count`,
`LinkMicMethodEvent.m_type` -> `message_type`, `LinkLayerEvent.list_content`
-> `list_change_content`. `WebsocketResponseEvent` holds the frame in `raw`
instead of inheriting it, so the class-order trap above is gone there.
`_parse_webcast_response_message` also takes the frame.

Compiled modules in a 7.0.1 install: `pydantic_core` (required),
`websockets.speedups` and protobuf's `_upb` (both have pure-Python
fallbacks). `protobuf3-to-dict` has no wheel; 7.0.1 does not import it.

Comparison on 2026-10-13 (`tools/compare_libs.py`): three public lives, 20
minutes each, about 6800 events. Every event the add-on uses (joins, likes,
viewer counts, comments, social, shares, follows, gifts, link mic and link
layer, live end, control) decodes to the same events with the same values in
both versions once the renames are mapped. Differences only in events the
add-on ignores: 7.0.1 no longer maps `GameServerFeatureEvent`,
`PrivilegeAdvanceEvent`, `StreamStatusEvent`, `AnchorToolModificationEvent`
and `GiftGalleryEvent`, adds `ViewerPicksUpdateEvent`, and fills
`BarrageEvent.user`. 6.6.5 connected to all three lives. This compares
decoding only, not connecting (sign server, websocket handshake), where
TikTok changes usually break old versions.

Every connection goes through the Euler Stream sign server, which has free
community rate limits: keep live test connections few and long.

## What a viewer's connection does not carry

The add-on connects as an anonymous viewer; asked for two features on
2026-10-13, neither is possible reliably from that connection.

- All current viewers by name: the stream has the viewer count, the top 5 of
  the room's ranking (`RoomUserSeqEvent.ranks`, always 5 in the recordings)
  and joins, but no leaves, and TikTok samples joins in big rooms (about 2000
  joins for 4000 viewers in 20 minutes). Neither 7.0.1 nor EulerApiSdk has a
  request for a room's viewers.
- The host's verification puzzle: the protocol has
  `WebcastAccessControlMessage` (`captcha`: record id, room id, seconds to
  verify) and `WebcastRoomVerifyMessage`. In 19 public lives watched for 17
  hours (`tools/record_live.py`, which prints these as they come) neither
  arrived; besides the usual messages there were only `WebcastControlMessage`
  pause (`extra.source` "app_pause", the host left the app), unpause and end,
  and `WebcastStreamStatusMessage` (field 2.3: 2 stream up, 3 down). Most
  likely TikTok sends the verification to the host's app only; from outside
  it is not known whether any of those hosts got a puzzle. Only a recording
  of a live whose host notes when the puzzle came can settle it.
  Connecting with the host's session cookie might receive it, but the cookie
  gives full access to the account and goes to the sign server.
