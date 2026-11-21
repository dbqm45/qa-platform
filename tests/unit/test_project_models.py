"""Tests for Project, Repository and Environment models (TASK-006, part 1)."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qa_schemas.project import Environment, Project, Repository


def _project_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "shop",
        "name": "Shop",
        "repositories": [
            {"name": "web", "path": "../shop-web"},
            {"name": "api", "url": "https://example.com/org/shop-api"},
        ],
        "environments": [
            {
                "name": "local",
                "base_url": "http://localhost:3000",
                "services": {"api": "http://localhost:8000"},
            },
            {"name": "staging", "base_url": "https://staging.example.com", "timeout_seconds": 60},
        ],
        "default_environment": "local",
    }
    data.update(overrides)
    return data


# --- Valid data --------------------------------------------------------------


def test_valid_project_is_parsed_with_types() -> None:
    project = Project.model_validate(_project_data())

    assert project.repositories[0].path == Path("../shop-web")
    assert str(project.repositories[1].url) == "https://example.com/org/shop-api"
    local = project.environment("local")
    assert local is not None
    assert str(local.services["api"]) == "http://localhost:8000/"
    assert project.scenario_dir == Path("scenarios")


def test_defaults() -> None:
    project = Project(id="minimal", name="Minimal")
    assert project.repositories == ()
    assert project.environments == ()
    assert project.default_environment is None
    assert Environment(name="local").timeout_seconds == 30.0


def test_name_is_stripped() -> None:
    assert Project(id="p", name="  Shop  ").name == "Shop"


def test_environment_lookup_returns_none_for_unknown_name() -> None:
    assert Project.model_validate(_project_data()).environment("prod") is None


# --- JSON round trip ---------------------------------------------------------


def test_project_json_round_trip() -> None:
    project = Project.model_validate(_project_data())
    restored = Project.model_validate_json(project.model_dump_json())
    assert restored == project


def test_json_uses_plain_types() -> None:
    dumped = Project.model_validate(_project_data()).model_dump(mode="json")
    assert dumped["repositories"][0]["path"] == "../shop-web"
    assert dumped["environments"][1]["base_url"] == "https://staging.example.com/"


# --- Invalid data ------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["", "Shop", "1shop", "shop app", "shop.app", "a" * 65])
def test_invalid_identifier_is_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        Project.model_validate(_project_data(id=bad_id))


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 201])
def test_invalid_project_name_is_rejected(bad_name: str) -> None:
    with pytest.raises(ValidationError, match="name"):
        Project.model_validate(_project_data(name=bad_name))


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Project.model_validate(_project_data(enviroments=[]))


def test_models_are_immutable() -> None:
    project = Project.model_validate(_project_data())
    with pytest.raises(ValidationError, match="frozen"):
        project.name = "Other"  # type: ignore[misc]


def test_repository_requires_a_location() -> None:
    with pytest.raises(ValidationError, match="at least one of 'path' or 'url'"):
        Repository(name="web")


def test_duplicate_repository_names_are_rejected() -> None:
    repos = [{"name": "web", "path": "a"}, {"name": "web", "path": "b"}]
    with pytest.raises(ValidationError, match=r"duplicate repository names: \['web'\]"):
        Project.model_validate(_project_data(repositories=repos))


def test_duplicate_environment_names_are_rejected() -> None:
    envs = [{"name": "qa"}, {"name": "qa"}]
    with pytest.raises(ValidationError, match=r"duplicate environment names: \['qa'\]"):
        Project.model_validate(_project_data(environments=envs, default_environment=None))


def test_default_environment_must_exist() -> None:
    with pytest.raises(ValidationError, match="default_environment 'prod' is not defined"):
        Project.model_validate(_project_data(default_environment="prod"))


@pytest.mark.parametrize(
    "url",
    ["not a url", "ftp://example.com", "file:///etc/passwd", "localhost:3000"],
)
def test_invalid_url_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="base_url"):
        Environment(name="local", base_url=url)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    ["https://user:secret@example.com", "https://token@example.com/repo"],
)
def test_url_with_credentials_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="must not contain credentials"):
        Repository(name="web", url=url)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="must not contain credentials"):
        Environment(name="local", services={"api": url})  # type: ignore[dict-item]


@pytest.mark.parametrize("timeout", [0, -1, 3601])
def test_invalid_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValidationError, match="timeout_seconds"):
        Environment(name="local", timeout_seconds=timeout)


def test_invalid_service_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="services"):
        Environment(name="local", services={"My API": "http://localhost"})  # type: ignore[dict-item]


# --- Environment variables and headers (TASK-055) ----------------------------


def test_environment_variables_and_headers() -> None:
    environment = Environment(
        name="qa",
        variables={"SHOP_USER": "alice", "LOCALE": "pl"},
        headers={
            "Accept-Language": "pl",
            "X-Api-Key": "${SHOP_API_KEY}",
            "Authorization": "Bearer ${API_TOKEN}",
        },
    )
    assert environment.variables["SHOP_USER"] == "alice"
    assert environment.headers["Authorization"] == "Bearer ${API_TOKEN}"


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"X-Api-Key": "abc123"}, "header X-Api-Key must reference a secret"),
        ({"Authorization": "Bearer abc"}, "header Authorization must reference a secret"),
        ({"cookie": "session=1"}, "header cookie must reference a secret"),
        ({"Bad Header": "x"}, "headers"),
    ],
)
def test_plaintext_credentials_in_headers_are_rejected(
    headers: dict[str, str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Environment(name="qa", headers=headers)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("SHOP_PASSWORD", "looks like a secret"),
        ("API_TOKEN", "looks like a secret"),
        ("STRIPE_KEY", "looks like a secret"),
        ("CLIENT_SECRET", "looks like a secret"),
        ("shop_user", "variables"),
        ("1USER", "variables"),
    ],
)
def test_invalid_or_secret_variables_are_rejected(name: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Environment(name="qa", variables={name: "x"})
