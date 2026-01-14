from app.domain.clients.service import evaluate_churn
from app.settings import settings


def test_churn_scoring_distinguishes_frequent_from_dormant():
    frequent = evaluate_churn(
        days_since_last_completed=7,
        avg_gap_days=14,
        complaint_count=0,
        avg_rating=4.8,
        low_rating_count=0,
    )
    dormant = evaluate_churn(
        days_since_last_completed=settings.client_churn_days_since_last_high + 10,
        avg_gap_days=14,
        complaint_count=0,
        avg_rating=4.8,
        low_rating_count=0,
    )
    assert frequent.risk_band == "LOW"
    assert dormant.risk_band == "HIGH"
