import asyncio
import email
import email.policy
import email.utils
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.base import ChannelAdapter, InboundEvent
from app.channels.contact_resolver import resolve_contact
from app.config import settings
from app.core import event_bus

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
POLL_INTERVAL_SECONDS = 60
MAX_MESSAGES_PER_POLL = 20


def is_configured() -> bool:
    """The Gmail adapter is idle unless both the address and app password are set."""
    return bool(settings.gmail_address and settings.gmail_app_password)


@dataclass
class ParsedEmail:
    sender_email: str
    sender_name: str
    subject: str
    body: str
    message_id: str
    thread_id: str
    sent_at: datetime


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"<[^>]+>", "", text)).strip()


def parse_email(raw: bytes, fallback_id: str) -> ParsedEmail:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    name, address = email.utils.parseaddr(str(msg["From"] or ""))

    message_id = str(msg["Message-ID"] or "").strip() or f"<{fallback_id}@gmail.local>"
    references = str(msg["References"] or "").split()
    in_reply_to = str(msg["In-Reply-To"] or "").strip()
    thread_id = references[0] if references else (in_reply_to or message_id)

    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part is not None else ""
    if body_part is not None and body_part.get_content_type() == "text/html":
        body = _strip_html(body)

    subject = str(msg["Subject"] or "").strip()
    while True:
        stripped = re.sub(r"(?i)^\s*(re|fwd?)\s*:\s*", "", subject)
        if stripped == subject:
            break
        subject = stripped

    try:
        sent_at = email.utils.parsedate_to_datetime(str(msg["Date"]))
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        sent_at = datetime.now(timezone.utc)

    return ParsedEmail(
        sender_email=address.lower(),
        sender_name=name,
        subject=subject or "(no subject)",
        body=body.strip(),
        message_id=message_id,
        thread_id=thread_id,
        sent_at=sent_at,
    )


class GmailAdapter(ChannelAdapter):
    channel = "gmail"

    def to_event(self, payload: dict[str, Any]) -> InboundEvent:
        """payload: {"email": ParsedEmail, "org_id", "account_id", "contact_id"}."""
        parsed: ParsedEmail = payload["email"]
        return InboundEvent(
            channel=self.channel,
            external_thread_id=parsed.thread_id,
            external_message_id=parsed.message_id,
            author={"type": "contact", "id": payload["contact_id"]},
            body=parsed.body or parsed.subject,
            occurred_at=parsed.sent_at,
            org_id=payload["org_id"],
            account_id=payload["account_id"],
            title=parsed.subject[:80],
        )


_adapter = GmailAdapter()


def _connect() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(settings.gmail_address, settings.gmail_app_password.replace(" ", ""))
    imap.select("INBOX")
    return imap


def _fetch_unseen_blocking() -> list[tuple[bytes, bytes]]:
    """Returns [(imap_uid, raw_rfc822)]. BODY.PEEK leaves messages unread until we've handled them."""
    imap = _connect()
    try:
        _, data = imap.uid("SEARCH", None, "UNSEEN")
        uids = data[0].split()[:MAX_MESSAGES_PER_POLL]
        fetched = []
        for uid in uids:
            _, parts = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                fetched.append((uid, raw))
        return fetched
    finally:
        imap.logout()


def _mark_seen_blocking(uids: list[bytes]) -> None:
    if not uids:
        return
    imap = _connect()
    try:
        for uid in uids:
            imap.uid("STORE", uid, "+FLAGS", "\\Seen")
    finally:
        imap.logout()


async def process_raw_email(session_factory: async_sessionmaker[AsyncSession], uid: bytes, raw: bytes) -> None:
    """Parse one RFC822 message, resolve its sender to a contact, and push the canonical event."""
    parsed = parse_email(raw, fallback_id=f"uid-{uid.decode()}")
    if not parsed.sender_email or parsed.sender_email == settings.gmail_address.lower():
        return  # unparseable sender, or our own mailbox (avoid echo loops)

    async with session_factory() as session:
        resolved = await resolve_contact(session, email=parsed.sender_email, name=parsed.sender_name)
    event = _adapter.to_event(
        {
            "email": parsed,
            "org_id": resolved.org_id,
            "account_id": resolved.account_id,
            "contact_id": resolved.contact_id,
        }
    )
    await event_bus.publish(event)


async def poll_once(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """One IMAP pass: fetch unread mail, push each onto the bus, then mark it read. Returns count handled."""
    fetched = await asyncio.to_thread(_fetch_unseen_blocking)
    handled: list[bytes] = []
    for uid, raw in fetched:
        try:
            await process_raw_email(session_factory, uid, raw)
            handled.append(uid)
        except Exception:  # noqa: BLE001 -- leave it unread so the next poll retries
            logger.exception("failed to process gmail message uid=%s", uid)
    await asyncio.to_thread(_mark_seen_blocking, handled)
    return len(handled)


async def run_poller(
    session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = POLL_INTERVAL_SECONDS
) -> None:
    """Background task: poll Gmail over IMAP forever. Returns immediately (idle) if credentials are blank."""
    if not is_configured():
        logger.info("gmail adapter idle: GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")
        return
    while True:
        try:
            await poll_once(session_factory)
        except Exception:  # noqa: BLE001 -- network/auth hiccup; try again next tick
            logger.exception("gmail poll failed")
        await asyncio.sleep(interval_seconds)
