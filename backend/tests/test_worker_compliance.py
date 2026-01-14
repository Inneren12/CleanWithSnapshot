from datetime import date, timedelta
from types import SimpleNamespace

from app.domain.workers.compliance import (
    CertificateSnapshot,
    missing_required_certificates,
    onboarding_progress,
    required_certificates_for_skills,
)


def test_missing_required_certificates_clears_after_addition():
    skills = ["window_cleaning"]
    missing = missing_required_certificates(skills, [])
    assert "Ladder Safety" in missing

    certificates = [
        CertificateSnapshot(
            name="Ladder Safety",
            status="active",
            expires_at=date.today() + timedelta(days=30),
        )
    ]
    missing_after_add = missing_required_certificates(skills, certificates, reference_date=date.today())
    assert missing_after_add == []


def test_required_certificates_for_skills_normalizes_skill_names():
    requirements = {"window_cleaning": ["Ladder Safety"]}
    for skill in ["Window Cleaning", "window_cleaning", "WINDOW_CLEANING"]:
        required = required_certificates_for_skills([skill], requirements)
        assert required == ["Ladder Safety"]


def test_missing_required_certificates_handles_mixed_case_skills():
    requirements = {"window_cleaning": ["Ladder Safety"]}
    missing = missing_required_certificates(["Window Cleaning"], [], requirements=requirements)
    assert missing == ["Ladder Safety"]


def test_onboarding_progress_counts_completed_items():
    onboarding = SimpleNamespace(
        docs_received=True,
        background_check=False,
        training_completed=True,
        first_booking_done=False,
    )
    completed, total = onboarding_progress(onboarding)
    assert completed == 2
    assert total == 4
