from ipaddress import ip_address
import logging

from starlette.requests import Request

from app.infra.security import get_client_ip, resolve_client_key
from app.settings import settings


def _make_request(
    client_host: str,
    xff: str | None = None,
    forwarded: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    if forwarded is not None:
        headers.append((b"forwarded", forwarded.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": headers,
        "client": (client_host, 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


def test_forwarded_does_not_override_xff_when_both_present() -> None:
    request = _make_request(
        client_host="10.0.0.10",
        xff="1.2.3.4",
        forwarded="for=9.9.9.9",
    )

    resolved_ip = get_client_ip(request, ["10.0.0.0/8"])

    assert ip_address(resolved_ip) == ip_address("1.2.3.4")


def test_forwarded_used_only_when_xff_missing() -> None:
    request = _make_request(
        client_host="10.0.0.10",
        forwarded="for=9.9.9.9",
    )

    resolved_ip = get_client_ip(request, ["10.0.0.0/8"])

    assert ip_address(resolved_ip) == ip_address("9.9.9.9")


def test_invalid_cidr_does_not_widen_trust(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_ips", [])
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", ["203.0.113.5/24"])
    request = _make_request(client_host="203.0.113.42", xff="1.2.3.4")

    with caplog.at_level(logging.WARNING):
        resolved_ip = resolve_client_key(
            request,
            trust_proxy_headers=True,
            trusted_proxy_ips=settings.trusted_proxy_ips,
            trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
        )

    assert resolved_ip == "203.0.113.42"
    assert any(
        rec.levelno >= logging.WARNING and "invalid_trusted_proxy_cidr" in rec.getMessage()
        for rec in caplog.records
    )


def test_valid_cidr_trusts_correctly(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_ips", [])
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", ["203.0.113.0/24"])
    request = _make_request(client_host="203.0.113.42", xff="1.2.3.4")

    resolved_ip = resolve_client_key(
        request,
        trust_proxy_headers=True,
        trusted_proxy_ips=settings.trusted_proxy_ips,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )

    assert ip_address(resolved_ip) == ip_address("1.2.3.4")
