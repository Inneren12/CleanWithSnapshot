import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class PricingConfig:
    pricing_config_id: str
    pricing_config_version: str
    config_hash: str
    data: Dict[str, Any]


def _canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _resolve_pricing_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    module_candidate = Path(__file__).resolve().parents[3] / candidate
    if module_candidate.exists():
        return module_candidate
    raise FileNotFoundError(f"Pricing config not found at {path}")


def load_pricing_config(path: str) -> PricingConfig:
    resolved_path = _resolve_pricing_path(path)
    content = resolved_path.read_text(encoding="utf-8")
    data = json.loads(content)
    canonical = _canonical_json(data)
    config_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return PricingConfig(
        pricing_config_id=data["pricing_config_id"],
        pricing_config_version=str(data["pricing_config_version"]),
        config_hash=f"sha256:{config_hash}",
        data=data,
    )
