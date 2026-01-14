from datetime import date, timedelta
from types import SimpleNamespace

from app.domain.workers.compliance import CertificateSnapshot, missing_required_certificates, onboarding_progress


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
