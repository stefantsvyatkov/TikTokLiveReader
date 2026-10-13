# TikTokLive notes

Vendored version 6.6.5 (MIT). Newer: 6.6.6 and 7.0.1 (AGPL-3.0 with a
section 7 exception allowing integration into non-SaaS software).

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
library modules (`lib/secrets.py`) are not private. Scopes are counted, so
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
