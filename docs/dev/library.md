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
the vendored modules only inside `vendor_loader.runtime_scope`.

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

Every connection goes through the Euler Stream sign server, which has free
community rate limits: keep live test connections few and long.
