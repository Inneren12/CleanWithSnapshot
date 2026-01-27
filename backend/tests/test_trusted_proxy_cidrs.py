from app.infra.security import is_trusted_proxy_peer
from app.settings import Settings


def test_trusted_proxy_cidrs_match_ipv4_and_ipv6():
    settings = Settings(
        trust_proxy_headers=True,
        trusted_proxy_cidrs="172.28.0.0/16,::1/128",
        _env_file=None,
    )

    assert is_trusted_proxy_peer("172.28.10.20", settings.trusted_proxy_ips, settings.trusted_proxy_cidrs)
    assert is_trusted_proxy_peer("::1", settings.trusted_proxy_ips, settings.trusted_proxy_cidrs)


def test_trusted_proxy_cidrs_reject_out_of_range():
    settings = Settings(
        trust_proxy_headers=True,
        trusted_proxy_cidrs="172.28.0.0/16",
        _env_file=None,
    )

    assert not is_trusted_proxy_peer("10.0.0.5", settings.trusted_proxy_ips, settings.trusted_proxy_cidrs)
