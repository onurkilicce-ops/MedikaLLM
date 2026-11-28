"""
Password complexity validation as enforced by the Pydantic model.

The same rules are duplicated in the React form for instant feedback —
when these tests change, frontend/src/pages/{Login,Register}.jsx must be
updated to match. Both layers reject before the request is processed,
but the server is the one we trust.
"""
import pytest
from pydantic import ValidationError

from src.auth.models import RegisterRequest


def _build_request(password: str) -> RegisterRequest:
    """Helper: a minimal valid registration payload with a swappable password."""
    return RegisterRequest(
        email="user@example.com",
        password=password,
        name="Test User",
        account_type="user",
    )


@pytest.mark.parametrize(
    "password",
    [
        "Aa1!aaaa",       # exactly the minimum: 8 chars, all classes
        "Strong#123",
        "Complex!Password9",
        "P@ssw0rd1",
    ],
)
def test_accepts_valid_password(password):
    """Spot-checks that everyday passwords passing the rules are accepted."""
    req = _build_request(password)
    assert req.password == password


@pytest.mark.parametrize(
    "password,reason",
    [
        ("alllowercase1!", "missing uppercase"),
        ("ALLUPPERCASE1!", "missing lowercase"),
        ("NoNumbers!", "missing digit"),
        ("NoSpecial1", "missing special character"),
        ("Pass1!", "too short (< 8 chars)"),
        ("Aa1!", "way under 8 chars"),
        ("", "empty string"),
    ],
)
def test_rejects_weak_password(password, reason):
    """Each entry violates at least one rule; the model must raise."""
    with pytest.raises(ValidationError, match="Password|password"):
        _build_request(password)


def test_rejects_password_missing_special():
    """Spelling out the special-char rule end-to-end so a regression
    in the validator regex (e.g. someone removes a punctuation char from
    the allowed set) shows up here."""
    with pytest.raises(ValidationError) as excinfo:
        _build_request("NoSpecialChar1")
    # The exact message lives in the Pydantic error chain; we just
    # confirm 'special' is mentioned so this catches a renamed message.
    assert "special" in str(excinfo.value).lower()


# --- ChangePasswordRequest: bcrypt's 72-byte limit (R1-O1-D1 / D2) ----------
# bcrypt>=5 raises ValueError for secrets over 72 BYTES; the request model must
# reject them (422) instead of letting the hash step fail (500). The limit is
# on UTF-8 bytes, not characters.

def _change(new_password: str):
    from src.auth.models import ChangePasswordRequest

    return ChangePasswordRequest(current_password="x", new_password=new_password)


@pytest.mark.parametrize(
    "new_password, n_bytes",
    [
        ("Aa1!" + "x" * 68, 72),               # ASCII, exactly 72 bytes
        ("Aa1!" + "ü" * 34, 72),          # 38 characters, 72 bytes (u-umlaut = 2 bytes)
        ("Aa1!" + "€" * 22 + "xx", 72),   # euro sign = 3 bytes
    ],
    ids=["ascii-72", "two-byte-72", "three-byte-72"],
)
def test_change_password_accepts_exactly_72_utf8_bytes(new_password, n_bytes):
    import bcrypt

    assert len(new_password.encode("utf-8")) == n_bytes
    req = _change(new_password)
    assert req.new_password == new_password  # not truncated
    bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=4))  # hashable


@pytest.mark.parametrize(
    "new_password, n_chars, n_bytes",
    [
        ("Aa1!" + "x" * 69, 73, 73),
        ("Aa1!" + "ü" * 35, 39, 74),
        ("Aa1!" + "€" * 23, 27, 73),
    ],
    ids=["ascii-73", "two-byte-74", "three-byte-73"],
)
def test_change_password_rejects_over_72_utf8_bytes(new_password, n_chars, n_bytes):
    assert (len(new_password), len(new_password.encode("utf-8"))) == (n_chars, n_bytes)
    with pytest.raises(ValidationError, match="72 bytes"):
        _change(new_password)
