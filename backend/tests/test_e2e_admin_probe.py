from importlib import util
from pathlib import Path


def _load_probe_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "e2e_admin_probe.py"
    spec = util.spec_from_file_location("e2e_admin_probe", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load e2e_admin_probe module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_signed_headers_contains_required_values(monkeypatch):
    monkeypatch.setenv("ADMIN_PROXY_AUTH_SECRET", "proxy-secret")
    monkeypatch.setenv("ADMIN_PROXY_AUTH_E2E_USER", "e2e-user")
    monkeypatch.setenv("ADMIN_PROXY_AUTH_E2E_EMAIL", "e2e@example.com")
    monkeypatch.setenv("ADMIN_PROXY_AUTH_E2E_ROLES", "admin")
    monkeypatch.setenv("ADMIN_PROXY_AUTH_E2E_SECRET", "e2e-secret")

    probe_module = _load_probe_module()
    config = probe_module.build_probe_config()
    headers = probe_module.build_signed_headers(config)

    assert headers["X-Proxy-Auth-Secret"] == "proxy-secret"
    assert headers["X-Auth-MFA"] == "true"
    assert headers["X-E2E-Admin-User"] == "e2e-user"
    assert headers["X-E2E-Admin-Email"] == "e2e@example.com"
    assert headers["X-E2E-Admin-Roles"] == "admin"
    assert headers["X-E2E-Proxy-Timestamp"] == config.timestamp
    assert headers["X-E2E-Proxy-Signature"]
