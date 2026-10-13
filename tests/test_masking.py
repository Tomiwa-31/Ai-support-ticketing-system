import pytest

from app.ai.masking import Masker, luhn_valid, unmask

VISA = "4111 1111 1111 1111"  # standard test number, passes Luhn


def test_luhn():
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


def test_masks_email_and_is_case_insensitive_and_stable():
    m = Masker()
    out = m.mask("Mail jamie@acme.com or JAMIE@ACME.COM, cc dana@commsworth.com")
    assert out == "Mail [EMAIL_1] or [EMAIL_1], cc [EMAIL_2]"
    assert m.mapping == {"[EMAIL_1]": "jamie@acme.com", "[EMAIL_2]": "dana@commsworth.com"}


@pytest.mark.parametrize("card", [VISA, "4111-1111-1111-1111", "4111111111111111", "378282246310005"])
def test_masks_valid_card_numbers(card):
    m = Masker()
    out = m.mask(f"my card is {card} thanks")
    assert out == "my card is [CARD_1] thanks"
    assert card not in out


def test_long_digit_run_failing_luhn_is_masked_as_account_not_left_in_clear():
    out = Masker().mask("account 4111111111111112 please")
    assert "4111111111111112" not in out
    assert "[ACCOUNT_1]" in out


@pytest.mark.parametrize("phone", ["+234 801 234 5678", "+2348012345678", "555-123-4567", "(555) 123-4567"])
def test_masks_phone_numbers(phone):
    out = Masker().mask(f"call me on {phone} now")
    assert phone not in out
    assert "[PHONE_" in out or "[ACCOUNT_" in out


def test_plain_account_numbers_are_masked():
    out = Masker().mask("acct 0123456789 and BVN 22334455667")
    assert "0123456789" not in out and "22334455667" not in out


def test_ordinary_numbers_and_dates_are_left_alone():
    text = "Order 12345 placed 2026-10-09, 3 items, total 1,250.00 USD"
    assert Masker().mask(text) == text


def test_same_value_gets_same_token_across_texts():
    m = Masker()
    assert m.mask("card 4111111111111111") == "card [CARD_1]"
    assert m.mask("again 4111 1111 1111 1111") == "again [CARD_1]"
    assert m.mapping == {"[CARD_1]": "4111111111111111"}


def test_masking_is_idempotent():
    m = Masker()
    once = m.mask(f"a@b.com {VISA}")
    assert m.mask(once) == once


def test_unmask_restores_only_email_and_phone():
    m = Masker()
    masked = m.mask(f"jamie@acme.com {VISA} +234 801 234 5678 acct 0123456789")
    restored = unmask(masked, m.mapping)
    assert "jamie@acme.com" in restored
    assert "+234 801 234 5678" in restored
    assert "[CARD_1]" in restored and "[ACCOUNT_1]" in restored
    assert "4111" not in restored and "0123456789" not in restored


def test_unmask_ignores_tokens_the_model_invented():
    assert unmask("hello [EMAIL_9]", {}) == "hello [EMAIL_9]"


def test_card_cut_short_by_a_title_truncation_is_still_masked():
    out = Masker().mask("Hi, I was charged twice. My card is 4111 1111 1")
    assert "4111" not in out and "1111" not in out
    assert out.startswith("Hi, I was charged twice. My card is [ACCOUNT_1]")


def test_a_plus_number_that_happens_to_pass_the_card_checksum_is_still_a_phone():
    # 2348025550147 passes Luhn by coincidence; it must not become a card (cards are never given to tools, phones can be).
    assert luhn_valid("2348025550147")
    m = Masker()
    assert m.mask("call +234 802 555 0147 now") == "call [PHONE_1] now"
    assert unmask("[PHONE_1]", m.mapping) == "+234 802 555 0147"
