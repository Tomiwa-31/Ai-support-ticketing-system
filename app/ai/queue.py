"""The AI queue: separate from the event bus so slow model calls never block message ingestion (or Slack's 3 s ack)."""
import asyncio

_queue: "asyncio.Queue[int]" = asyncio.Queue()


def request(issue_id: int) -> None:
    """Ask the AI worker to look at an issue's latest customer message."""
    _queue.put_nowait(issue_id)


async def get() -> int:
    return await _queue.get()


def task_done() -> None:
    _queue.task_done()


def reset() -> None:
    """Fresh queue (tests: each test runs on its own event loop)."""
    global _queue
    _queue = asyncio.Queue()
