import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent
from app.channels.contact_resolver import resolve_contact
from app.config import settings
from app.core import event_bus

logger = logging.getLogger(__name__)

SIGNATURE_MAX_AGE_SECONDS = 60 * 5


def is_configured() -> bool:
    """The Slack adapter is inert unless a signing secret is set."""
    return bool(settings.slack_signing_secret)


def verify_signature(body: bytes, timestamp: str | None, signature: str | None) -> bool:
    if not (timestamp and signature and settings.slack_signing_secret):
        return False
    try:
        if abs(time.time() - int(timestamp)) > SIGNATURE_MAX_AGE_SECONDS:
            return False
    except ValueError:
        return False
    basestring = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(settings.slack_signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def should_process(slack_event: dict[str, Any]) -> bool:
    """Only plain human messages: no edits/joins/bot posts (which also keeps us from echo loops)."""
    return (
        slack_event.get("type") == "message"
        and not slack_event.get("subtype")
        and not slack_event.get("bot_id")
        and bool(slack_event.get("user"))
        and bool((slack_event.get("text") or "").strip())
    )


def _users_info_blocking(user_id: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://slack.com/api/users.info?" + urllib.parse.urlencode({"user": user_id}),
        headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


async def fetch_user_profile(user_id: str) -> dict[str, str]:
    """Best-effort email/name for a Slack user; falls back to a placeholder identity."""
    fallback = {"email": f"{user_id.lower()}@slack.invalid", "name": user_id}
    if not settings.slack_bot_token:
        return fallback
    try:
        data = await asyncio.to_thread(_users_info_blocking, user_id)
    except Exception:  # noqa: BLE001 -- network/Slack failure shouldn't drop the message
        logger.exception("slack users.info failed for %s", user_id)
        return fallback
    user = data.get("user") or {}
    if not data.get("ok") or user.get("is_bot"):
        return fallback
    profile = user.get("profile") or {}
    return {
        "email": profile.get("email") or fallback["email"],
        "name": user.get("real_name") or profile.get("real_name") or fallback["name"],
    }


class SlackAdapter(ChannelAdapter):
    channel = "slack"

    def to_event(self, payload: dict[str, Any]) -> InboundEvent:
        """payload: {"event": <Slack message event>, "org_id", "account_id", "contact_id"}."""
        slack_event = payload["event"]
        slack_channel = slack_event["channel"]
        ts = slack_event["ts"]
        text = slack_event["text"]
        return InboundEvent(
            channel=self.channel,
            external_thread_id=f"{slack_channel}:{slack_event.get('thread_ts') or ts}",
            external_message_id=slack_event.get("client_msg_id") or f"{slack_channel}:{ts}",
            author={"type": "contact", "id": payload["contact_id"]},
            body=text,
            occurred_at=datetime.fromtimestamp(float(ts), tz=timezone.utc),
            org_id=payload["org_id"],
            account_id=payload["account_id"],
            title=text.strip().splitlines()[0][:80],
        )


_adapter = SlackAdapter()


async def handle_event(session_factory: async_sessionmaker[AsyncSession], slack_event: dict[str, Any]) -> None:
    """Resolve the Slack user to a contact, convert to the canonical event, push it on the bus."""
    if not should_process(slack_event):
        return
    try:
        profile = await fetch_user_profile(slack_event["user"])
        async with session_factory() as session:
            resolved = await resolve_contact(session, email=profile["email"], name=profile["name"])
        event = _adapter.to_event(
            {
                "event": slack_event,
                "org_id": resolved.org_id,
                "account_id": resolved.account_id,
                "contact_id": resolved.contact_id,
            }
        )
        await event_bus.publish(event)
    except Exception:  # noqa: BLE001 -- runs as a background task; log instead of dying silently
        logger.exception("failed to handle slack event")


#slack adapeter essentially takes the slack event and converts it into a canonical event that the system can understand.which will be used to create an issue and message in the system