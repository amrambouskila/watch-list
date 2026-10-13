"""The root docker-compose.yml, parsed the way compose itself reads it (before variable substitution)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml

COMPOSE_PATH: Final[Path] = Path(__file__).resolve().parents[3] / "docker-compose.yml"
# An optional bind address on the front of a `[ip:]host:container` publication. Matched rather than split
# on, because `${TV_POSTGRES_PORT:-5525}` carries a colon of its own and would break a naive split.
_BIND_ADDRESS: Final[re.Pattern[str]] = re.compile(r"^(?P<address>\d{1,3}(?:\.\d{1,3}){3}|\[[^\]]+\]):")


def compose_document() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def compose_service(name: str) -> dict[str, Any]:
    return compose_document()["services"][name]


def split_publication(mapping: str | Mapping[str, Any]) -> tuple[str | None, str, str]:
    """One port publication -> (bind address or None, host port, container port).

    Accepts both forms compose allows: the `[ip:]host:container` short string and the long mapping
    (`{host_ip, published, target}`). A long-form entry stringified instead of read would come out as a
    dict repr, which no guard here would recognise as a port.
    """
    if isinstance(mapping, Mapping):
        address = mapping.get("host_ip")
        published = mapping.get("published")
        target = mapping.get("target")
        return (
            str(address) if address is not None else None,
            "" if published is None else str(published),
            "" if target is None else str(target),
        )
    match = _BIND_ADDRESS.match(mapping)
    address = match.group("address") if match else None
    remainder = mapping[match.end() :] if match else mapping
    host, _, container = remainder.rpartition(":")
    return address, host, container


def published_host_ports(document: Mapping[str, Any] | None = None) -> list[str]:
    """The host port of every publication, bind address stripped, in file order."""
    services = (document if document is not None else compose_document())["services"]
    ports: list[str] = []
    for service in services.values():
        for mapping in service.get("ports", []):
            ports.append(split_publication(mapping)[1])
    return ports
