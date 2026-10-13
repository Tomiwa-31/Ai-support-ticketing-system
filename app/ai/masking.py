"""Rule-based masking of sensitive values. Runs BEFORE any text is sent to a model (or, later, an embedding API).

Each distinct value becomes a stable token like [EMAIL_1]; the token->value map stays server-side in the Masker
and is never sent anywhere. Rules are deliberately conservative (over-masking is safe, under-masking is not).
"""
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 13-19 digits, optionally grouped by single spaces or dashes; confirmed with the Luhn check below.
_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
# International (+...) numbers, and separated national numbers such as 555-123-4567 or (555) 123 4567.
_PHONE_PLUS = re.compile(r"(?<![\w])\+\d[\d ().-]{7,}\d(?!\w)")
_PHONE_SEPARATED = re.compile(r"(?<![\w])\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4}(?:[ .-]\d{2,4})?(?!\w)")
# Any other run of 8+ digits, or 9+ digits grouped by single spaces/dashes: account numbers, BVN/NIN-style ids, phone
# numbers, and card numbers that failed Luhn or were cut short (e.g. by an 80-character title).
_LONG_NUMBER = re.compile(r"(?<![\w-])(?:\d{8,}|\d(?:[ -]?\d){8,})(?![\w-])")

_TOKEN = re.compile(r"\[(EMAIL|PHONE|CARD|ACCOUNT)_\d+\]")

# Kinds that are safe to put back into a draft reply shown to an agent. Card and account numbers never are.
RESTORABLE_KINDS = ("EMAIL", "PHONE")


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class Masker:
    """Stateful per model call: the same value always gets the same token across all texts masked by one instance."""

    def __init__(self) -> None:
        self._token_by_value: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}
        self.mapping: dict[str, str] = {}  # token -> original value (server-side only)

    def _token(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key not in self._token_by_value:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            token = f"[{kind}_{self._counts[kind]}]"
            self._token_by_value[key] = token
            self.mapping[token] = value
        return self._token_by_value[key]

    def mask(self, text: str) -> str:
        text = _EMAIL.sub(lambda m: self._token("EMAIL", m.group(0).lower()), text)
        # International numbers first: a "+234 802 555 0147" has the digit count of a card and passes the card checksum
        # by chance about one time in ten, and would otherwise be taken for one.
        text = _PHONE_PLUS.sub(lambda m: self._token("PHONE", m.group(0)), text)
        text = _CARD.sub(self._mask_card, text)
        text = _LONG_NUMBER.sub(lambda m: self._token("ACCOUNT", m.group(0)), text)
        text = _PHONE_SEPARATED.sub(lambda m: self._token("PHONE", m.group(0)), text)
        return text

    def _mask_card(self, match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            return self._token("CARD", digits)
        return match.group(0)  # not a card; a later rule may still mask it as an account number


def find_tokens(text: str) -> list[str]:
    """Mask placeholders still present in text (e.g. a draft the agent has not cleaned up)."""
    return [m.group(0) for m in _TOKEN.finditer(text)]


def unmask(text: str, mapping: dict[str, str], kinds: tuple[str, ...] = RESTORABLE_KINDS) -> str:
    """Put real values back for the allowed kinds only; any other token is left as a placeholder."""

    def restore(match: re.Match) -> str:
        if match.group(1) in kinds:
            return mapping.get(match.group(0), match.group(0))
        return match.group(0)

    return _TOKEN.sub(restore, text)
