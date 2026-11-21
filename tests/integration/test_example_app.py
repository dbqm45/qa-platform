"""The example application behaves as documented (TASK-070)."""

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

import pytest


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


@pytest.fixture
def url(shop_server: Any) -> str:
    shop_server.state.reset()
    return str(shop_server.url)


def _request(
    url: str,
    method: str = "GET",
    *,
    form: dict[str, str] | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    data = None
    all_headers = dict(headers or {})
    if form is not None:
        data = urlencode(form).encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=all_headers)
    try:
        with _opener.open(request) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def _sign_in(url: str, username: str, password: str) -> tuple[int, dict[str, str], str]:
    return _request(f"{url}/login", "POST", form={"username": username, "password": password})


def _token(url: str, username: str = "alice", password: str = "correct-password") -> str:
    _, _, text = _request(
        f"{url}/api/login", "POST", body={"username": username, "password": password}
    )
    return str(json.loads(text)["token"])


# --- Login page --------------------------------------------------------------


def test_login_page_has_testable_elements(url: str) -> None:
    status, _, text = _request(f"{url}/login")
    assert status == 200
    assert "<label>Username" in text and 'type="password"' in text
    assert 'data-testid="login-button">Log in</button>' in text


def test_successful_login_leads_to_dashboard(url: str) -> None:
    status, headers, _ = _sign_in(url, "alice", "correct-password")
    assert (status, headers["Location"]) == (303, "/dashboard")
    cookie = headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in headers["Set-Cookie"]

    status, _, text = _request(f"{url}/dashboard", headers={"Cookie": cookie})
    assert status == 200
    assert 'data-testid="greeting">Welcome, Alice</p>' in text


def test_dashboard_requires_sign_in(url: str) -> None:
    status, headers, _ = _request(f"{url}/dashboard")
    assert (status, headers["Location"]) == (303, "/login")


def test_logout_ends_the_session(url: str) -> None:
    _, headers, _ = _sign_in(url, "alice", "correct-password")
    cookie = headers["Set-Cookie"].split(";")[0]
    _request(f"{url}/logout", "POST", headers={"Cookie": cookie}, form={})
    status, _, _ = _request(f"{url}/dashboard", headers={"Cookie": cookie})
    assert status == 303


# --- Business rules 1 and 2 --------------------------------------------------


@pytest.mark.parametrize(("username", "password"), [("alice", "wrong"), ("nobody", "x")])
def test_wrong_credentials(url: str, username: str, password: str) -> None:
    status, _, text = _sign_in(url, username, password)
    assert status == 401
    assert 'role="alert" data-testid="login-error">Invalid username or password</p>' in text
    assert f'value="{username}"' in text  # username kept, password not


def test_missing_credentials(url: str) -> None:
    status, _, text = _sign_in(url, "", "")
    assert status == 401
    assert "Username and password are required" in text


def test_three_failed_sign_ins_lock_the_account(url: str) -> None:
    assert "Invalid username" in _sign_in(url, "alice", "x")[2]
    assert "Invalid username" in _sign_in(url, "alice", "y")[2]
    assert "Account locked" in _sign_in(url, "alice", "z")[2]
    status, _, text = _sign_in(url, "alice", "correct-password")
    assert (status, "Account locked" in text) == (401, True)
    assert _sign_in(url, "bob", "bob-password")[0] == 303  # other users unaffected


def test_successful_sign_in_resets_the_counter(url: str) -> None:
    _sign_in(url, "alice", "x")
    _sign_in(url, "alice", "y")
    _sign_in(url, "alice", "correct-password")
    assert "Invalid username" in _sign_in(url, "alice", "z")[2]


def test_reset_restores_the_initial_state(url: str) -> None:
    for attempt in ("a", "b", "c"):
        _sign_in(url, "alice", attempt)
    assert _request(f"{url}/api/reset", "POST", body={})[0] == 200
    assert _sign_in(url, "alice", "correct-password")[0] == 303


# --- Business rule 3: contact form -------------------------------------------

VALID_CONTACT = {
    "name": "Alice",
    "email": "alice@example.com",
    "topic": "order",
    "message": "Where is my order?",
    "consent": "on",
}


def test_valid_contact_form(url: str) -> None:
    status, _, text = _request(f"{url}/contact", "POST", form=VALID_CONTACT)
    assert status == 200
    assert 'data-testid="contact-success">Thank you, Alice!</h1>' in text


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"name": " "}, "Name is required"),
        ({"email": ""}, "Email is required"),
        ({"email": "alice.example.com"}, "Email must contain @"),
        ({"topic": ""}, "Topic is required"),
        ({"message": "x" * 201}, "Message must be at most 200 characters"),
        ({"consent": ""}, "Consent is required"),
    ],
)
def test_invalid_contact_form(url: str, changes: dict[str, str], error: str) -> None:
    status, _, text = _request(f"{url}/contact", "POST", form=VALID_CONTACT | changes)
    assert status == 422
    assert f"<li>{error}</li>" in text
    assert 'role="alert"' in text


def test_contact_form_keeps_entered_values_and_escapes_them(url: str) -> None:
    form = VALID_CONTACT | {"name": "<b>Eve</b>", "consent": ""}
    _, _, text = _request(f"{url}/contact", "POST", form=form)
    assert 'value="&lt;b&gt;Eve&lt;/b&gt;"' in text
    assert "<b>Eve</b>" not in text


# --- API and business rule 4 -------------------------------------------------


def test_health(url: str) -> None:
    status, headers, text = _request(f"{url}/api/health")
    assert (status, headers["Content-Type"], json.loads(text)) == (
        200,
        "application/json",
        {"status": "ok"},
    )


def test_api_login(url: str) -> None:
    status, _, text = _request(
        f"{url}/api/login", "POST", body={"username": "bob", "password": "bob-password"}
    )
    data = json.loads(text)
    assert status == 200
    assert data["name"] == "Bob" and len(data["token"]) > 10


@pytest.mark.parametrize(
    ("body", "status"),
    [({"username": "bob", "password": "x"}, 401), ([1, 2], 400), (None, 400)],
)
def test_api_login_errors(url: str, body: Any, status: int) -> None:
    payload = body if body is not None else ""  # "" is valid JSON, but not an object
    assert _request(f"{url}/api/login", "POST", body=payload)[0] == status


def test_api_login_of_locked_account_is_forbidden(url: str) -> None:
    for attempt in ("a", "b", "c"):
        _request(f"{url}/api/login", "POST", body={"username": "alice", "password": attempt})
    status, _, text = _request(
        f"{url}/api/login", "POST", body={"username": "alice", "password": "correct-password"}
    )
    assert (status, json.loads(text)) == (403, {"error": "Account locked"})


def test_create_and_list_orders(url: str) -> None:
    auth = {"Authorization": f"Bearer {_token(url)}"}

    status, _, text = _request(
        f"{url}/api/orders", "POST", body={"product": "pear", "quantity": 4}, headers=auth
    )

    assert status == 201
    assert json.loads(text) == {
        "id": 1,
        "user": "alice",
        "product": "pear",
        "quantity": 4,
        "total": 6.0,
    }
    _, _, listing = _request(f"{url}/api/orders", headers=auth)
    assert [o["product"] for o in json.loads(listing)["orders"]] == ["pear"]


def test_orders_are_per_user(url: str) -> None:
    alice = {"Authorization": f"Bearer {_token(url)}"}
    bob = {"Authorization": f"Bearer {_token(url, 'bob', 'bob-password')}"}
    _request(f"{url}/api/orders", "POST", body={"product": "plum", "quantity": 1}, headers=alice)
    assert json.loads(_request(f"{url}/api/orders", headers=bob)[2]) == {"orders": []}


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"product": "banana", "quantity": 1}, "product must be one of: apple, pear, plum"),
        ({"product": "apple", "quantity": 0}, "quantity must be an integer from 1 to 10"),
        ({"product": "apple", "quantity": 11}, "quantity must be an integer from 1 to 10"),
        ({"product": "apple", "quantity": "2"}, "quantity must be an integer from 1 to 10"),
        ({"product": "apple", "quantity": True}, "quantity must be an integer from 1 to 10"),
        ([], "Body must be a JSON object"),
    ],
)
def test_invalid_orders(url: str, body: Any, error: str) -> None:
    auth = {"Authorization": f"Bearer {_token(url)}"}
    status, _, text = _request(f"{url}/api/orders", "POST", body=body, headers=auth)
    assert status == 422
    assert error in json.loads(text)["errors"]


@pytest.mark.parametrize("header", [None, "Bearer nope", "Basic abc"])
def test_orders_need_a_valid_token(url: str, header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    status, _, text = _request(f"{url}/api/orders", headers=headers)
    assert (status, json.loads(text)) == (401, {"error": "Missing or invalid token"})


def test_unknown_routes(url: str) -> None:
    assert _request(f"{url}/nope")[0] == 404
    status, _, text = _request(f"{url}/api/nope")
    assert (status, json.loads(text)) == (404, {"error": "Not found"})
