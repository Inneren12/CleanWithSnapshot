from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re

from app.settings import settings


DEFAULT_SKILL_CERT_REQUIREMENTS: dict[str, list[str]] = {
    "window_cleaning": ["Ladder Safety"],
    "deep_clean": ["Chemical Handling"],
}

ONBOARDING_CHECKLIST_FIELDS: tuple[tuple[str, str], ...] = (
    ("docs_received", "Docs received"),
    ("background_check", "Background check"),
    ("training_completed", "Training completed"),
    ("first_booking_done", "First booking done"),
)


@dataclass(frozen=True)
class CertificateSnapshot:
    name: str
    status: str
    expires_at: date | None = None


def _normalize_certificate_name(name: str) -> str:
    return name.strip().lower()


def _normalize_skill_name(name: str) -> str:
    cleaned = name.strip().lower()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[\s-]+", "_", cleaned)
    cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


def _normalize_skill_requirements(
    requirements: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    if not requirements:
        return DEFAULT_SKILL_CERT_REQUIREMENTS
    normalized: dict[str, list[str]] = {}
    for skill, certs in requirements.items():
        if not isinstance(skill, str):
            continue
        cleaned = [cert.strip() for cert in certs if isinstance(cert, str) and cert.strip()]
        if cleaned:
            normalized[skill] = cleaned
    return normalized or DEFAULT_SKILL_CERT_REQUIREMENTS


def _load_requirements_from_settings() -> dict[str, list[str]]:
    raw = getattr(settings, "worker_skill_cert_requirements_raw", None)
    if not raw:
        return DEFAULT_SKILL_CERT_REQUIREMENTS
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return DEFAULT_SKILL_CERT_REQUIREMENTS
    if not isinstance(parsed, dict):
        return DEFAULT_SKILL_CERT_REQUIREMENTS
    return _normalize_skill_requirements(parsed)


def get_skill_cert_requirements() -> dict[str, list[str]]:
    return _load_requirements_from_settings()


def required_certificates_for_skills(
    skills: list[str] | None,
    requirements: dict[str, list[str]] | None = None,
) -> list[str]:
    requirements = _normalize_skill_requirements(requirements or get_skill_cert_requirements())
    normalized_requirements: dict[str, list[str]] = {}
    for skill, certs in requirements.items():
        if not isinstance(skill, str):
            continue
        normalized_skill = _normalize_skill_name(skill)
        if not normalized_skill:
            continue
        normalized_certs = normalized_requirements.setdefault(normalized_skill, [])
        for cert in certs:
            if cert not in normalized_certs:
                normalized_certs.append(cert)
    required_by_name: dict[str, str] = {}
    for skill in skills or []:
        if not isinstance(skill, str):
            continue
        normalized_skill = _normalize_skill_name(skill)
        cert_sources: list[str] = []
        if normalized_skill:
            cert_sources.extend(normalized_requirements.get(normalized_skill, []))
        if skill in requirements and skill != normalized_skill:
            cert_sources.extend(requirements.get(skill, []))
        for cert in cert_sources:
            normalized = _normalize_certificate_name(cert)
            if normalized:
                required_by_name.setdefault(normalized, cert)
    return sorted(required_by_name.values())


def certificate_is_valid(
    certificate: CertificateSnapshot,
    reference_date: date | None = None,
) -> bool:
    status = (certificate.status or "").strip().lower()
    if status != "active":
        return False
    if reference_date and certificate.expires_at and certificate.expires_at < reference_date:
        return False
    return True


def missing_required_certificates(
    skills: list[str] | None,
    certificates: list[CertificateSnapshot] | None,
    *,
    requirements: dict[str, list[str]] | None = None,
    reference_date: date | None = None,
) -> list[str]:
    required = required_certificates_for_skills(skills or [], requirements)
    required_by_normalized = {_normalize_certificate_name(cert): cert for cert in required}
    valid_cert_names = {
        _normalize_certificate_name(cert.name)
        for cert in certificates or []
        if certificate_is_valid(cert, reference_date)
    }
    missing = [
        required_by_normalized[name]
        for name in required_by_normalized
        if name not in valid_cert_names
    ]
    return sorted(missing)


def onboarding_progress(onboarding: object | None) -> tuple[int, int]:
    total = len(ONBOARDING_CHECKLIST_FIELDS)
    completed = 0
    for field_name, _label in ONBOARDING_CHECKLIST_FIELDS:
        if onboarding and getattr(onboarding, field_name, False):
            completed += 1
    return completed, total
