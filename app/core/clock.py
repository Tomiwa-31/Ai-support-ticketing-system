from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC. The app stamps every time it compares (SLA timers, audit rows) so one clock is used throughout."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
