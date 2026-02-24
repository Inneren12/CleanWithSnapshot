import pytest
from app.infra.encryption import blind_hash

def test_blind_hash_deterministic():
    val = "test@example.com"
    org_id = "org_123"

    h1 = blind_hash(val, org_id)
    h2 = blind_hash(val, org_id)

    assert h1 == h2
    assert len(h1) == 64 # SHA256 hex digest length

def test_blind_hash_diff_orgs():
    val = "test@example.com"
    org1 = "org_1"
    org2 = "org_2"

    h1 = blind_hash(val, org1)
    h2 = blind_hash(val, org2)

    assert h1 != h2

def test_blind_hash_diff_values():
    val1 = "test1"
    val2 = "test2"
    org = "org_1"

    h1 = blind_hash(val1, org)
    h2 = blind_hash(val2, org)

    assert h1 != h2
