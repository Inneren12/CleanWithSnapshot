"""Typed payload models for persistent jobs."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.errors import DomainError

class IncompatiblePayloadError(DomainError):
    """Raised when a job payload has an unsupported schema_version."""

    def __init__(self, job_type: str, version: int) -> None:
        message = f"Incompatible payload schema v{version} for job type '{job_type}'"
        super().__init__(
            detail=message,
            title="INCOMPATIBLE_PAYLOAD_VERSION",
            errors=[{"job_type": job_type, "schema_version": version}]
        )
        self.message = message
        self.error_code = "INCOMPATIBLE_PAYLOAD_VERSION"
        self.context = {"job_type": job_type, "schema_version": version}


class UnknownJobTypeError(DomainError):
    """Raised when a job_type has no registered payload model."""

    def __init__(self, job_type: str) -> None:
        message = f"Unknown job type: '{job_type}'"
        super().__init__(
            detail=message,
            title="UNKNOWN_JOB_TYPE",
            errors=[{"job_type": job_type}]
        )
        self.message = message
        self.error_code = "UNKNOWN_JOB_TYPE"
        self.context = {"job_type": job_type}

# Payload models — one per job_type
class CatalogSyncPayload(BaseModel):
    schema_version: int = 1

class CubeFetchPayload(BaseModel):
    schema_version: int = 1
    product_id: str

class TransformPayload(BaseModel):
    schema_version: int = 1
    source_keys: list[str]
    operations: list[dict[str, object]]
    output_key: str | None = None

class GraphicsGeneratePayload(BaseModel):
    schema_version: int = 1
    data_key: str
    chart_type: str
    title: str
    size: tuple[int, int] = (1200, 900)
    category: str = "housing"

CURRENT_SCHEMA_VERSION = 1

PAYLOAD_REGISTRY: dict[str, type[BaseModel]] = {
    "catalog_sync": CatalogSyncPayload,
    "cube_fetch": CubeFetchPayload,
    "transform": TransformPayload,
    "graphics_generate": GraphicsGeneratePayload,
}

def parse_payload(job_type: str, payload_json: str) -> BaseModel:
    cls = PAYLOAD_REGISTRY.get(job_type)
    if cls is None:
        raise UnknownJobTypeError(job_type)

    parsed = cls.model_validate_json(payload_json)

    if parsed.schema_version != CURRENT_SCHEMA_VERSION:
        raise IncompatiblePayloadError(job_type, parsed.schema_version)

    return parsed
