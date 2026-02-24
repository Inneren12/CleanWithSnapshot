"""harden legacy password hashes

Revision ID: 0090_harden_legacy_passwords
Revises: 0089_checkout_attempt
Create Date: 2026-03-01 10:00:00.000000

Migrates all unhardened legacy SHA256 password hashes to a PBKDF2-wrapped format.
This addresses the vulnerability where legacy hashes are stored as a single
round of SHA256, which is unsuitable for password storage at rest.

The migration uses 'Outer PBKDF2':
  NewHash = PBKDF2(OldSHA256Hash, salt, iterations)
This allows hardening existing hashes without requiring the original password.
"""

from __future__ import annotations

import hashlib
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

# Revision identifiers, used by Alembic.
revision = "0090_harden_legacy_passwords"
down_revision = "0089_checkout_attempt"
branch_labels = None
depends_on = None

LEGACY_SHA256_PREFIX = "sha256$"
DEFAULT_ITERATIONS = 600000

def harden_hash(stored_hash: str, iterations: int) -> str | None:
    if not stored_hash.startswith(LEGACY_SHA256_PREFIX):
        return None
    raw_content = stored_hash.removeprefix(LEGACY_SHA256_PREFIX)
    parts = raw_content.split("$")
    if len(parts) < 2 or parts[0] == "pbkdf2":
        # Already hardened or invalid
        return None

    # Format: sha256$salt$digest
    digest = parts[-1]
    salt = "$".join(parts[:-1])

    hardened_digest = hashlib.pbkdf2_hmac(
        "sha256",
        digest.encode(),
        salt.encode(),
        iterations,
    ).hex()

    return f"{LEGACY_SHA256_PREFIX}pbkdf2${iterations}${salt}${hardened_digest}"

def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    # Use a raw SQL query to avoid dependency on the User model which might change
    users = session.execute(
        sa.text("SELECT user_id, password_hash FROM users WHERE password_hash LIKE 'sha256$%'")
    ).fetchall()

    for user_id, password_hash in users:
        if password_hash and not password_hash.startswith("sha256$pbkdf2$"):
            new_hash = harden_hash(password_hash, DEFAULT_ITERATIONS)
            if new_hash:
                session.execute(
                    sa.text("UPDATE users SET password_hash = :new_hash WHERE user_id = :user_id"),
                    {"new_hash": new_hash, "user_id": user_id}
                )

    # Also handle workers if they have password hashes
    # Check if workers table exists first
    table_names = sa.inspect(bind).get_table_names()
    if "workers" in table_names:
        workers = session.execute(
            sa.text("SELECT worker_id, password_hash FROM workers WHERE password_hash LIKE 'sha256$%'")
        ).fetchall()
        for worker_id, password_hash in workers:
            if password_hash and not password_hash.startswith("sha256$pbkdf2$"):
                new_hash = harden_hash(password_hash, DEFAULT_ITERATIONS)
                if new_hash:
                    session.execute(
                        sa.text("UPDATE workers SET password_hash = :new_hash WHERE worker_id = :worker_id"),
                        {"new_hash": new_hash, "worker_id": worker_id}
                    )

    session.commit()

def downgrade() -> None:
    # Downgrade is not easily possible because we'd need to reverse PBKDF2
    # which is computationally expensive/impossible by design.
    # However, since this is a security hardening, we typically don't downgrade.
    pass
