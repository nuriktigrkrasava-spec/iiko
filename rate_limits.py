"""Rate limits use forwarded addresses only from explicitly trusted proxies."""
import ipaddress, os
from functools import lru_cache
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

@lru_cache(maxsize=8)
def _trusted(value):
    return tuple(ipaddress.ip_network(item.strip()) for item in value.split(",") if item.strip())


def _client_ip(request: Request) -> str:
    peer = get_remote_address(request)
    try:
        networks = _trusted(os.getenv("TRUSTED_PROXY_CIDRS", ""))
        current = ipaddress.ip_address(peer)
        trusted = any(current in network for network in networks)
        parts = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
        if trusted and parts:
            # Walk from the socket through known proxies. The first untrusted
            # address is the visitor; never trust arbitrary leftmost entries.
            for part in reversed(parts):
                current = ipaddress.ip_address(part)
                if not any(current in network for network in networks):
                    return str(current)
            return str(current)
    except ValueError:
        pass
    return peer

limiter = Limiter(key_func=_client_ip)
