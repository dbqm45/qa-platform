# Examples

| Path | What it is |
|------|------------|
| `app/shop_app.py` | **Example Shop**, a small application to test the platform against |
| `qa.yaml` | project configuration for the Example Shop |
| `scenarios/` | Gherkin scenarios for the Example Shop: `login.feature`, `contact.feature` (browser), `api.feature` (API), `orders.feature` (API + browser) |
| `specifications/`, `plans/` | sample Test Specification (compiled from the first login scenario) and Execution Plans, as schema reference |

## Example Shop

Standard library only; UI and API on one port.

```bash
uv run python examples/app/shop_app.py --port 8000
```

Then open <http://localhost:8000/login>.

| UI | Purpose |
|----|---------|
| `/login` | sign-in form (Username, Password, "Log in" with `data-testid="login-button"`) |
| `/dashboard` | "Welcome, <name>" (`data-testid="greeting"`) and the user's orders (`data-testid="orders"`, e.g. "apple (quantity 3)"), requires sign-in |
| `/contact` | contact form: Name, Email, Topic (select), Message, consent checkbox |

| API | Purpose |
|-----|---------|
| `GET /api/health` | `{"status": "ok"}` |
| `POST /api/login` | `{"username", "password"}` → `{"token", "name"}`; 401 wrong, 403 locked |
| `GET /api/orders` | the user's orders; needs `Authorization: Bearer <token>` |
| `POST /api/orders` | `{"product", "quantity"}` → 201 order or 422 `{"errors": [...]}` |
| `POST /api/reset` | restore the initial state (for repeatable tests) |

Test users: `alice` / `correct-password` (Alice), `bob` / `bob-password` (Bob),
`carol` / `carol-password` (Carol; the lockout scenario locks this account).

Business rules:

1. Wrong username or password → "Invalid username or password".
2. Three failed sign-ins lock the account → "Account locked" (until reset).
3. Contact form: name, email, topic and message are required; email must
   contain `@`; message at most 200 characters; consent is required.
4. Orders: product must be `apple`, `pear` or `plum`; quantity an integer 1–10.

State is kept in memory. The application is deliberately simple and not
secure: never expose it outside your machine.

## Running the scenarios

With the Example Shop running on port 8000:

```bash
cd examples
```

```bash
uv run qa init
```

```bash
uv run qa test --scenario login.feature
```

```bash
uv run qa test --scenario contact.feature
```

```bash
uv run qa test --scenario api.feature
```

```bash
uv run qa test --scenario orders.feature
```

The scenarios are repeatable without restarting the application: the
lockout scenario uses its own user (`carol`), whose account simply stays
locked. `POST /api/reset` restores everything.
