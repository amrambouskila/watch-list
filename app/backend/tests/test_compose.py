from __future__ import annotations

from typing import Final

import pytest

from compose_support import compose_document, compose_service, published_host_ports, split_publication

POSTGRES_HEALTHCHECK_COMMAND: Final[str] = "pg_isready -U ${TV_POSTGRES_USER:-tv} -d ${TV_POSTGRES_DB:-tv}"


def test_postgres_service_exists() -> None:
    assert "postgres" in compose_document()["services"]


def test_postgres_image_is_pinned_to_16_alpine() -> None:
    assert compose_service("postgres")["image"] == "postgres:16-alpine"


def test_postgres_restarts_unless_stopped() -> None:
    assert compose_service("postgres")["restart"] == "unless-stopped"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("POSTGRES_DB", "${TV_POSTGRES_DB:-tv}"),
        ("POSTGRES_USER", "${TV_POSTGRES_USER:-tv}"),
        ("POSTGRES_PASSWORD", "${TV_POSTGRES_PASSWORD:-tv}"),
    ],
)
def test_postgres_environment_substitutes_the_tv_variables(name: str, expected: str) -> None:
    assert compose_service("postgres")["environment"][name] == expected


def test_postgres_data_lives_on_the_named_volume() -> None:
    assert "tv_postgres_data:/var/lib/postgresql/data" in compose_service("postgres")["volumes"]


def test_tv_postgres_data_is_declared_as_a_named_volume() -> None:
    assert "tv_postgres_data" in compose_document()["volumes"]


def test_postgres_publishes_5525_onto_the_containers_5432() -> None:
    assert compose_service("postgres")["ports"] == ["127.0.0.1:${TV_POSTGRES_PORT:-5525}:5432"]


def test_postgres_binds_loopback_only() -> None:
    # Every listener in this project is loopback-only, and the database's default credentials are tv/tv, so
    # an all-interfaces bind would put a trivially-guessable database on whatever network the host is on.
    address, host, container = split_publication(compose_service("postgres")["ports"][0])
    assert address == "127.0.0.1"
    assert (host, container) == ("${TV_POSTGRES_PORT:-5525}", "5432")


def test_no_service_binds_the_shared_host_5432() -> None:
    # 5432 is the machine's single shared local PostgreSQL listener; a containerised Postgres never takes it.
    assert "5432" not in published_host_ports()


def test_the_shared_5432_guard_sees_through_a_long_form_publication() -> None:
    # Compose also accepts `{host_ip, published, target}`. Stringifying one would yield a dict repr, and a
    # host 5432 hidden inside it would sail past the guard above.
    long_form = {"services": {"rogue": {"ports": [{"published": "5432", "target": 5432}]}}}
    assert published_host_ports(long_form) == ["5432"]


def test_a_long_form_publication_splits_into_its_three_parts() -> None:
    assert split_publication({"host_ip": "127.0.0.1", "published": 5525, "target": 5432}) == (
        "127.0.0.1",
        "5525",
        "5432",
    )


def test_a_long_form_publication_without_a_bind_address_reports_none() -> None:
    assert split_publication({"published": "8096", "target": 8096}) == (None, "8096", "8096")


def test_postgres_healthcheck_is_cmd_shell_form() -> None:
    # `pg_isready -U ${...}` needs a shell for the substitution, so exec form would probe the literal string.
    assert compose_service("postgres")["healthcheck"]["test"] == ["CMD-SHELL", POSTGRES_HEALTHCHECK_COMMAND]


@pytest.mark.parametrize(
    ("key", "expected"),
    [("interval", "10s"), ("timeout", "5s"), ("retries", 5), ("start_period", "10s")],
)
def test_postgres_healthcheck_is_fully_specified(key: str, expected: str | int) -> None:
    assert compose_service("postgres")["healthcheck"][key] == expected


def test_backend_waits_for_postgres_to_be_healthy() -> None:
    # A bare depends_on list would start the backend before the server is accepting connections, and the
    # entrypoint's `alembic upgrade head` would fail on the first boot of a fresh volume.
    assert compose_service("backend")["depends_on"]["postgres"] == {"condition": "service_healthy"}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("TV_POSTGRES_HOST", "postgres"),
        ("TV_POSTGRES_PORT", "5432"),
        ("TV_POSTGRES_DB", "${TV_POSTGRES_DB:-tv}"),
        ("TV_POSTGRES_USER", "${TV_POSTGRES_USER:-tv}"),
        ("TV_POSTGRES_PASSWORD", "${TV_POSTGRES_PASSWORD:-tv}"),
    ],
)
def test_backend_reaches_postgres_by_service_name_on_the_container_port(name: str, expected: str) -> None:
    # 5525 is only the host publication; inside the network it is the service name and the container's 5432.
    assert compose_service("backend")["environment"][name] == expected


def test_backend_healthcheck_stays_exec_form_on_openapi_json() -> None:
    # It must never be pointed at anything that touches Postgres: a database blip would then mark the whole
    # API unhealthy and take the frontend down with it.
    probe = compose_service("backend")["healthcheck"]["test"]
    assert probe[0] == "CMD"
    assert "/openapi.json" in probe[-1]
    assert "postgres" not in " ".join(probe)
