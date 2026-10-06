from datetime import date

from server.extract.grounding import check_grounding, grounded
from server.extract.units import detect_unit, to_rupees
from server.extract.validate import validate_record
from server.parse.clean import normalize_for_match


# --- 1. normalize_for_match ---
def test_normalize_for_match():
    # Hyphen line breaks
    assert normalize_for_match("govern-\nance") == "governance"
    # Non-breaking spaces
    assert normalize_for_match("hello\u00a0world") == "hello world"
    # Curly quotes and case normalization
    assert normalize_for_match("“Quotes”") == '"quotes"'


# --- 2. Grounding (Exact, whitespace, paraphrase, short) ---
def test_grounded():
    page_text = "The board appointed Natarajan Chandrasekaran on 12th May."
    # Exact quote
    assert grounded("Natarajan Chandrasekaran on 12th", page_text) is True
    # Whitespace varied
    assert grounded("Natarajan   Chandrasekaran\non", page_text) is True
    # Paraphrase (should fail exact fuzzy check)
    assert grounded("Mr. Chandrasekaran was hired", page_text) is False
    # Short quote (< 8 chars)
    assert grounded("board", page_text) is False


# --- 3. Numeric & Person Grounding ---
class MockEvidence:
    def __init__(self, quote, page=1):
        self.quote = quote
        self.page = page


class MockRec:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        if "quote" in kwargs:
            self.evidence = MockEvidence(kwargs["quote"])


def test_numeric_grounding():
    parsed = {"pages": [{"page_no": 1, "cleaned_text": "Total revenue is 15.2 crores"}]}

    # Pass: Number is in the quote
    rec_pass = MockRec(amount_inr=15.2, amount_raw="15.2", quote="Total revenue is 15.2 crores")
    status, reason = check_grounding(rec_pass, parsed)
    assert status == "accepted"

    # Fail: Number invented by LLM, quote is just text
    rec_fail = MockRec(amount_inr=16.5, amount_raw="16.5", quote="Total revenue is 15.2 crores")
    status, reason = check_grounding(rec_fail, parsed)
    assert status == "rejected"
    assert reason == "ungrounded_number"


def test_person_grounding():
    parsed = {"pages": [{"page_no": 1, "cleaned_text": "Mr. Natarajan Chandrasekaran joined."}]}

    # Pass: Surname is in the quote
    rec_pass = MockRec(
        person_name="Natarajan Chandrasekaran", quote="Natarajan Chandrasekaran joined"
    )
    status, _ = check_grounding(rec_pass, parsed)
    assert status == "accepted"

    # Fail: Surname invented by LLM
    rec_fail = MockRec(person_name="Natarajan Smith", quote="Natarajan Chandrasekaran joined")
    status, reason = check_grounding(rec_fail, parsed)
    assert status == "rejected"
    assert reason == "ungrounded_surname"


# --- 4. Units ---
def test_units():
    assert detect_unit("₹ in crore") == "crore"
    assert detect_unit("Rs. in lakhs") == "lakhs"
    assert detect_unit("Amount in Mn") == "mn"
    assert detect_unit("Random text") is None

    assert to_rupees(1.5, "crore") == 15000000.0
    assert to_rupees(2.0, "lakhs") == 200000.0
    assert to_rupees(5.0, None) is None


# --- 5. Validation rules ---
def test_validation_rules():
    # din_format: valid
    rec = MockRec(person_name="John", din="12345678", evidence=MockEvidence("Valid quote"))
    assert validate_record(rec)[0] == "accepted"

    # din_format: invalid (should be set to None, not rejected)
    rec_bad_din = MockRec(person_name="John", din="123", evidence=MockEvidence("Valid quote"))
    validate_record(rec_bad_din)
    assert rec_bad_din.din is None

    # pct_range: > 100
    rec_pct_bad = MockRec(person_name="John", pct_holding=150, evidence=MockEvidence("Valid quote"))
    assert validate_record(rec_pct_bad) == ("rejected", "pct_out_of_range")

    # amount_nonneg
    rec_neg = MockRec(counterparty_name="X", amount_inr=-500, evidence=MockEvidence("Valid quote"))
    assert validate_record(rec_neg) == ("rejected", "amount_negative")

    # date_order
    rec_dates = MockRec(
        person_name="John",
        appointed_on=date(2023, 1, 1),
        ceased_on=date(2022, 1, 1),
        evidence=MockEvidence("Valid quote"),
    )
    assert validate_record(rec_dates) == ("review", "date_order_invalid")

    # name_is_not_role
    rec_role = MockRec(person_name="Company Secretary", evidence=MockEvidence("Valid quote"))
    assert validate_record(rec_role) == ("rejected", "name_is_role")


def test_role_words_only_match_whole_words():
    # "George" contains "geo"/"or", "Pierceon" contains "ceo": neither is a role.
    for name in ("Pierceon Dsa", "Officerwala Homi", "N Chandrasekaran"):
        rec = MockRec(person_name=name, evidence=MockEvidence("Valid quote"))
        assert validate_record(rec)[0] == "accepted", name
    for title in ("Chairman", "Chief Financial Officer", "Managing Director"):
        rec = MockRec(person_name=title, evidence=MockEvidence("Valid quote"))
        assert validate_record(rec) == ("rejected", "name_is_role"), title
