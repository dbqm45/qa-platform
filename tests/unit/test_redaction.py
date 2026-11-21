"""Secret references and redaction (TASK-066)."""

import pytest

from qa_core.redaction import MASK, MissingSecretError, Redactor, resolve_references


def test_known_values_are_masked() -> None:
    redactor = Redactor(["s3cret-value"])
    assert (
        redactor.redact("typed s3cret-value twice: s3cret-value") == f"typed {MASK} twice: {MASK}"
    )


def test_longest_secret_is_masked_first() -> None:
    redactor = Redactor(["abcd", "abcdefgh"])
    assert redactor.redact("x abcdefgh y abcd") == f"x {MASK} y {MASK}"


def test_very_short_values_are_not_masked_as_substrings() -> None:
    redactor = Redactor(["abc"])
    assert redactor.redact("abc is everywhere: abcdef") == "abc is everywhere: abcdef"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "/welcome?email=a%40b.c&password=hunter2&x=1",
            f"/welcome?email=a%40b.c&password={MASK}&x=1",
        ),
        ("token=abc123 and api_key=K-9", f"token={MASK} and api_key={MASK}"),
        ("PASSWD=x", f"PASSWD={MASK}"),
        ("?password=&next=/", "?password=&next=/"),
        ("Authorization: Bearer eyJhbGciOi.payload.sig", f"Authorization: Bearer {MASK}"),
        ("basic dXNlcjpwYXNz", f"basic {MASK}"),
        ("nothing sensitive here: page=2&sort=asc", "nothing sensitive here: page=2&sort=asc"),
        (
            '{"username": "alice", "password": "pw"}',
            f'{{"username": "alice", "password": "{MASK}"}}',
        ),
        ('{"token":"a\\"b", "name": "Alice"}', f'{{"token":"{MASK}", "name": "Alice"}}'),
        ('{"Token": ""}', '{"Token": ""}'),
    ],
)
def test_sensitive_patterns_are_masked_without_known_values(text: str, expected: str) -> None:
    assert Redactor().redact(text) == expected


def test_redact_nested_data() -> None:
    redactor = Redactor(["top-secret"])
    data = {"url": "/x?token=1234", "errors": ["top-secret leaked"], "count": 3, "ok": None}
    assert redactor.redact_data(data) == {
        "url": f"/x?token={MASK}", "errors": [f"{MASK} leaked"], "count": 3, "ok": None,
    }  # fmt: skip


def test_resolve_reference_registers_the_value() -> None:
    redactor = Redactor()
    value = resolve_references("pw: ${SHOP_PASSWORD}", {"SHOP_PASSWORD": "p@ss-w0rd"}, redactor)
    assert value == "pw: p@ss-w0rd"
    assert redactor.redact("p@ss-w0rd") == MASK


def test_text_without_references_is_unchanged() -> None:
    assert (
        resolve_references("plain ${lowercase} $NAME", {}, Redactor()) == "plain ${lowercase} $NAME"
    )


def test_missing_secret_names_the_variable_but_no_value() -> None:
    with pytest.raises(MissingSecretError, match="secret API_TOKEN is not set") as info:
        resolve_references("${API_TOKEN}", {"OTHER": "x"}, Redactor())
    assert info.value.name == "API_TOKEN"


def test_plain_variables_are_used_first_and_not_masked() -> None:
    redactor = Redactor()
    value = resolve_references(
        "${SHOP_USER} / ${SHOP_PASSWORD}",
        {"SHOP_USER": "from-os-env", "SHOP_PASSWORD": "s3cret-pw"},
        redactor,
        plain={"SHOP_USER": "alice"},
    )
    assert value == "alice / s3cret-pw"
    assert redactor.redact("alice s3cret-pw") == f"alice {MASK}"
