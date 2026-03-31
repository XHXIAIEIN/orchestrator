"""
Address Scheme Registry — unified addressing for multi-backend message routing.

Stolen from: Claude Code peerAddress.ts (SendMessageTool unified router)
Pattern: One parseAddress() function, route by scheme to different backends.

Replaces ad-hoc if/else routing with structured scheme dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AddressScheme(Enum):
    DOCKER = "docker"      # docker:<container-name>
    LOCAL = "local"        # local:<agent-id> (in-process Agent SDK)
    TELEGRAM = "tg"        # tg:<chat-id>
    WEBSOCKET = "ws"       # ws:<session-id> (Dashboard)
    REDIS = "redis"        # redis:<channel> (pub/sub)
    WECHAT = "wx"          # wx:<user-id>


@dataclass(frozen=True)
class ParsedAddress:
    scheme: AddressScheme
    target: str
    raw: str

    @property
    def is_local(self) -> bool:
        return self.scheme in (AddressScheme.LOCAL, AddressScheme.DOCKER)


def parse_address(address: str) -> ParsedAddress:
    """Parse a unified address string into scheme + target.

    Supports:
        docker:collector-chrome → AddressScheme.DOCKER, "collector-chrome"
        local:analyst           → AddressScheme.LOCAL, "analyst"
        tg:123456              → AddressScheme.TELEGRAM, "123456"
        ws:session-abc         → AddressScheme.WEBSOCKET, "session-abc"
        redis:events           → AddressScheme.REDIS, "events"
        wx:user123             → AddressScheme.WECHAT, "user123"

    Bare names (no colon) default to LOCAL scheme.
    """
    if ":" not in address:
        return ParsedAddress(scheme=AddressScheme.LOCAL, target=address, raw=address)

    scheme_str, _, target = address.partition(":")
    scheme_str = scheme_str.lower()

    scheme_map = {s.value: s for s in AddressScheme}
    scheme = scheme_map.get(scheme_str)

    if scheme is None:
        raise ValueError(
            f"Unknown address scheme '{scheme_str}' in '{address}'. "
            f"Valid schemes: {', '.join(scheme_map.keys())}"
        )

    if not target:
        raise ValueError(f"Empty target in address '{address}'")

    return ParsedAddress(scheme=scheme, target=target, raw=address)
