"""Resolve a hostname to every address it answers with."""

from __future__ import annotations

import asyncio
import socket


async def resolve_addresses(host: str, port: int) -> list[str]:
    """Every address `host` resolves to, as strings."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]
