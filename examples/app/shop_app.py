"""Example Shop: a small application for trying out and testing the QA platform (TASK-070).

Standard library only. UI and API are served from one port:

    uv run python examples/app/shop_app.py --port 8000

UI                                        API (JSON)
  GET  /login, POST /login                  GET  /api/health
  GET  /dashboard   (signed in)             POST /api/login      {username, password} -> token
  POST /logout                              GET  /api/orders     (Authorization: Bearer <token>)
  GET  /contact, POST /contact              POST /api/orders     {product, quantity}
                                            POST /api/reset      restore the initial state

Business rules
  1. Wrong username or password -> "Invalid username or password".
  2. Three failed sign-ins lock the account -> "Account locked".
  3. Contact form: name, email, topic, message required; email must contain "@";
     message at most 200 characters; consent must be given.
  4. Orders: product must be in the catalog; quantity an integer from 1 to 10.

Test users: alice / correct-password (Alice), bob / bob-password (Bob),
carol / carol-password (Carol, used by the lockout scenario).
The state lives in memory; POST /api/reset restores it so tests are repeatable.
This is an example application: it is not secure and must not be exposed.
"""

import argparse
import html
import json
import secrets
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

USERS = {
    "alice": {"password": "correct-password", "name": "Alice"},
    "bob": {"password": "bob-password", "name": "Bob"},
    "carol": {"password": "carol-password", "name": "Carol"},
}
CATALOG = {"apple": 1.20, "pear": 1.50, "plum": 0.80}
TOPICS = {"order": "Order question", "delivery": "Delivery", "other": "Something else"}
MAX_FAILED_SIGN_INS = 3
MAX_MESSAGE = 200


@dataclass
class ShopState:
    failed_sign_ins: dict[str, int] = field(default_factory=dict)
    sessions: dict[str, str] = field(default_factory=dict)
    """Session or API token -> username."""
    orders: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self.lock:
            self.failed_sign_ins.clear()
            self.sessions.clear()
            self.orders.clear()

    def sign_in(self, username: str, password: str) -> tuple[str | None, str | None]:
        """(token, error) according to business rules 1 and 2."""
        with self.lock:
            if not username or not password:
                return None, "Username and password are required"
            if self.failed_sign_ins.get(username, 0) >= MAX_FAILED_SIGN_INS:
                return None, "Account locked"
            user = USERS.get(username)
            if user is None or user["password"] != password:
                self.failed_sign_ins[username] = self.failed_sign_ins.get(username, 0) + 1
                if self.failed_sign_ins[username] >= MAX_FAILED_SIGN_INS:
                    return None, "Account locked"
                return None, "Invalid username or password"
            self.failed_sign_ins.pop(username, None)
            token = secrets.token_urlsafe(16)
            self.sessions[token] = username
            return token, None


def validate_contact(form: dict[str, str]) -> list[str]:
    """Business rule 3."""
    errors = []
    for name, label in (("name", "Name"), ("email", "Email"), ("message", "Message")):
        if not form.get(name, "").strip():
            errors.append(f"{label} is required")
    if form.get("email") and "@" not in form["email"]:
        errors.append("Email must contain @")
    if form.get("topic") not in TOPICS:
        errors.append("Topic is required")
    if len(form.get("message", "")) > MAX_MESSAGE:
        errors.append(f"Message must be at most {MAX_MESSAGE} characters")
    if form.get("consent") != "on":
        errors.append("Consent is required")
    return errors


def validate_order(body: Any) -> list[str]:
    """Business rule 4."""
    if not isinstance(body, dict):
        return ["Body must be a JSON object"]
    errors = []
    if body.get("product") not in CATALOG:
        errors.append(f"product must be one of: {', '.join(sorted(CATALOG))}")
    quantity = body.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 10:
        errors.append("quantity must be an integer from 1 to 10")
    return errors


# --- HTML --------------------------------------------------------------------


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)} - Example Shop</title>
<style>body{{font-family:sans-serif;max-width:32rem;margin:2rem auto}}
label{{display:block;margin:.5rem 0}}[role=alert]{{color:#b00}}</style></head>
<body><nav><a href="/login">Sign in</a> | <a href="/contact">Contact</a></nav>
<main>{body}</main></body></html>"""


def login_page(error: str = "", username: str = "") -> str:
    alert = f'<p role="alert" data-testid="login-error">{html.escape(error)}</p>' if error else ""
    return page(
        "Sign in",
        f"""<h1>Sign in</h1>{alert}
<form method="post" action="/login">
  <label>Username
    <input name="username" value="{html.escape(username)}" autocomplete="username"></label>
  <label>Password <input name="password" type="password" autocomplete="current-password"></label>
  <button type="submit" data-testid="login-button">Log in</button>
</form>""",
    )


def dashboard_page(name: str) -> str:
    return page(
        "Dashboard",
        f"""<h1>Dashboard</h1><p data-testid="greeting">Welcome, {html.escape(name)}</p>
<form method="post" action="/logout"><button type="submit">Log out</button></form>""",
    )


def contact_page(errors: list[str] | None = None, form: dict[str, str] | None = None) -> str:
    form = form or {}
    items = "".join(f"<li>{html.escape(e)}</li>" for e in errors or [])
    alert = f'<ul role="alert" data-testid="contact-errors">{items}</ul>' if errors else ""
    options = "".join(
        f'<option value="{key}"{" selected" if form.get("topic") == key else ""}>{label}</option>'
        for key, label in TOPICS.items()
    )

    def value(name: str) -> str:
        return html.escape(form.get(name, ""))

    return page(
        "Contact",
        f"""<h1>Contact us</h1>{alert}
<form method="post" action="/contact">
  <label>Name <input name="name" value="{value("name")}"></label>
  <label>Email <input name="email" value="{value("email")}"></label>
  <label>Topic <select name="topic">
    <option value="">Choose a topic</option>{options}
  </select></label>
  <label>Message <textarea name="message">{value("message")}</textarea></label>
  <label><input type="checkbox" name="consent"> I agree to be contacted</label>
  <button type="submit">Send</button>
</form>""",
    )


# --- HTTP --------------------------------------------------------------------


class ShopHandler(BaseHTTPRequestHandler):
    server: "ShopServer"
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.verbose:
            super().log_message(format, *args)

    # Routing

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        state = self.server.state
        if path in ("/", "/login"):
            self._html(login_page())
        elif path == "/dashboard":
            username = state.sessions.get(self._cookie("session") or "")
            if username is None:
                self._redirect("/login")
            else:
                self._html(dashboard_page(USERS[username]["name"]))
        elif path == "/contact":
            self._html(contact_page())
        elif path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
        elif path == "/api/orders":
            username = self._api_user()
            if username is not None:
                own = [o for o in state.orders if o["user"] == username]
                self._json(HTTPStatus.OK, {"orders": own})
        else:
            self._not_found()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        state = self.server.state
        if path == "/login":
            form = self._form()
            token, error = state.sign_in(form.get("username", ""), form.get("password", ""))
            if token is None:
                self._html(
                    login_page(error or "", form.get("username", "")), HTTPStatus.UNAUTHORIZED
                )
            else:
                self._redirect(
                    "/dashboard", cookie=f"session={token}; HttpOnly; Path=/; SameSite=Lax"
                )
        elif path == "/logout":
            state.sessions.pop(self._cookie("session") or "", None)
            self._redirect("/login", cookie="session=; Max-Age=0; Path=/")
        elif path == "/contact":
            form = self._form()
            errors = validate_contact(form)
            if errors:
                self._html(contact_page(errors, form), HTTPStatus.UNPROCESSABLE_ENTITY)
            else:
                name = html.escape(form["name"].strip())
                self._html(
                    page("Thank you", f'<h1 data-testid="contact-success">Thank you, {name}!</h1>')
                )
        elif path == "/api/login":
            body = self._json_body()
            if not isinstance(body, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Body must be a JSON object"})
                return
            token, error = state.sign_in(
                str(body.get("username", "")), str(body.get("password", ""))
            )
            if token is None:
                status = (
                    HTTPStatus.FORBIDDEN if error == "Account locked" else HTTPStatus.UNAUTHORIZED
                )
                self._json(status, {"error": error})
            else:
                name = USERS[str(body["username"])]["name"]
                self._json(HTTPStatus.OK, {"token": token, "name": name})
        elif path == "/api/orders":
            username = self._api_user()
            if username is None:
                return
            body = self._json_body()
            errors = validate_order(body)
            if errors:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"errors": errors})
                return
            with state.lock:
                order = {
                    "id": len(state.orders) + 1,
                    "user": username,
                    "product": body["product"],
                    "quantity": body["quantity"],
                    "total": round(CATALOG[body["product"]] * body["quantity"], 2),
                }
                state.orders.append(order)
            self._json(HTTPStatus.CREATED, order)
        elif path == "/api/reset":
            state.reset()
            self._json(HTTPStatus.OK, {"status": "reset"})
        else:
            self._not_found()

    # Helpers

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(min(length, 100_000))

    def _form(self) -> dict[str, str]:
        parsed = parse_qs(self._body().decode("utf-8", "replace"), keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items()}

    def _json_body(self) -> Any:
        try:
            return json.loads(self._body() or b"null")
        except json.JSONDecodeError:
            return None

    def _cookie(self, name: str) -> str | None:
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        return cookies[name].value if name in cookies else None

    def _api_user(self) -> str | None:
        header = self.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        username = self.server.state.sessions.get(token)
        if username is None:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Missing or invalid token"})
        return username

    def _send(self, status: int, content_type: str, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str, status: int = HTTPStatus.OK) -> None:
        self._send(status, "text/html; charset=utf-8", text.encode(), {})

    def _json(self, status: int, data: Any) -> None:
        self._send(status, "application/json", json.dumps(data).encode(), {})

    def _redirect(self, location: str, cookie: str | None = None) -> None:
        headers = {"Location": location}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send(HTTPStatus.SEE_OTHER, "text/plain", b"", headers)

    def _not_found(self) -> None:
        if self.path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        else:
            self._html(page("Not found", "<h1>Not found</h1>"), HTTPStatus.NOT_FOUND)


class ShopServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], verbose: bool = False) -> None:
        super().__init__(address, ShopHandler)
        self.state = ShopState()
        self.verbose = verbose

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        name = host.decode() if isinstance(host, bytes) else host
        return f"http://{name}:{port}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--quiet", action="store_true", help="do not log requests")
    args = parser.parse_args()
    server = ShopServer((args.host, args.port), verbose=not args.quiet)
    print(f"Example Shop running at {server.url} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
