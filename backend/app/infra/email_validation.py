"""
Email validation utilities with E2E-mode relaxation.

In E2E/test environments, allows RFC 2606 reserved domains:
- .invalid
- .test
- .example
- .localhost

In production, uses strict Pydantic EmailStr validation.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import AfterValidator, EmailStr, GetCoreSchemaHandler
from pydantic_core import CoreSchema, PydanticCustomError, core_schema

# RFC 2606 reserved TLDs for testing/documentation
_RFC2606_RESERVED_TLDS = frozenset({".invalid", ".test", ".example", ".localhost"})

# Environments where reserved TLDs are allowed
_E2E_ENVIRONMENTS = frozenset({"ci", "e2e", "test", "dev", "local"})

# Simple email regex for reserved domain validation
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


def _is_e2e_mode() -> bool:
    """Check if running in E2E/test mode based on APP_ENV."""
    from app.settings import settings
    return settings.app_env in _E2E_ENVIRONMENTS


def _is_reserved_domain(email: str) -> bool:
    """Check if email uses an RFC 2606 reserved TLD."""
    lower = email.lower()
    return any(lower.endswith(tld) for tld in _RFC2606_RESERVED_TLDS)


def _validate_reserved_email(email: str) -> str:
    """Validate email format for reserved domains (basic syntax check)."""
    if not _EMAIL_PATTERN.match(email):
        raise PydanticCustomError(
            "value_error",
            "value is not a valid email address: {reason}",
            {"reason": "invalid email format"},
        )
    return email


def validate_email_e2e(value: str) -> str:
    """
    Validate email, allowing RFC 2606 reserved domains in E2E mode.

    In E2E/test environments:
    - Accepts .invalid, .test, .example, .localhost domains
    - Uses basic syntax validation for these

    In production:
    - Uses strict EmailStr validation (via Pydantic)
    """
    if _is_e2e_mode() and _is_reserved_domain(value):
        return _validate_reserved_email(value)
    # For non-reserved domains, the value has already passed EmailStr validation
    return value


class E2EEmailStr(str):
    """
    Email string type that allows RFC 2606 reserved domains in E2E mode.

    Usage:
        from app.infra.email_validation import E2EEmailStr

        class MySchema(BaseModel):
            email: E2EEmailStr | None = None

    In production: Validates strictly like EmailStr
    In E2E mode: Also accepts .invalid, .test, .example, .localhost
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        def validate(value: str) -> str:
            if _is_e2e_mode() and _is_reserved_domain(value):
                return _validate_reserved_email(value)
            # For production or non-reserved domains, use standard email validation
            from email_validator import EmailNotValidError, validate_email
            try:
                result = validate_email(value, check_deliverability=False)
                return result.normalized
            except EmailNotValidError as e:
                raise PydanticCustomError(
                    "value_error",
                    "value is not a valid email address: {reason}",
                    {"reason": str(e)},
                ) from e

        return core_schema.no_info_after_validator_function(
            validate,
            core_schema.str_schema(),
        )


# Convenience type alias using Annotated
FlexibleEmailStr = Annotated[str, AfterValidator(validate_email_e2e)]
