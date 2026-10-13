"""Split an article into chunks for embedding: paragraph-aware, each chunk carries the article title for context."""

MAX_CHARS = 900


def chunk_article(title: str, body: str, max_chars: int = MAX_CHARS) -> list[str]:
    paragraphs = [p.strip() for p in body.replace("\r\n", "\n").split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        # A single over-long paragraph is cut on sentence-ish boundaries so no chunk exceeds the limit.
        pieces = [paragraph] if len(paragraph) <= max_chars else _split_long(paragraph, max_chars)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return [f"{title}\n\n{chunk}" for chunk in chunks] or [title]


def _split_long(text: str, max_chars: int) -> list[str]:
    pieces, current = [], ""
    for sentence in text.replace(". ", ".\n").split("\n"):
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    # A sentence longer than the limit on its own is hard-cut.
    return [piece[i : i + max_chars] for piece in pieces for i in range(0, len(piece), max_chars)]
