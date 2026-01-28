from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.infra.environment import DEV_DEFAULT_ENVIRONMENTS, SECURE_ENVIRONMENTS

logger = logging.getLogger(__name__)

REQUIRED_SECRET_KEYS = (
    "AUTH_SECRET_KEY",
    "CLIENT_PORTAL_SECRET",
    "WORKER_PORTAL_SECRET",
    "ADMIN_PROXY_AUTH_SECRET",
)


def load_secrets_backend(backend: str, app_env: str, config: dict[str, Any]) -> dict[str, Any]:
    backend = backend.strip().lower()
    if backend not in {"aws_secrets_manager", "aws_ssm"}:
        raise ValueError(f"Unsupported SECRETS_BACKEND: {backend}")

    if backend == "aws_secrets_manager":
        return _load_from_secrets_manager(app_env, config)
    return _load_from_ssm(app_env, config)


def _load_from_secrets_manager(app_env: str, config: dict[str, Any]) -> dict[str, Any]:
    region = (
        config.get("aws_region")
        or config.get("AWS_REGION")
        or config.get("AWS_DEFAULT_REGION")
        or config.get("AWS_SECRETS_MANAGER_REGION")
    )
    secret_id = (
        config.get("aws_secrets_manager_secret_id")
        or config.get("AWS_SECRETS_MANAGER_SECRET_ID")
        or config.get("AWS_SECRETS_MANAGER_SECRET_ARN")
    )
    explicit_json = config.get("aws_secrets_manager_secret_json") or config.get(
        "AWS_SECRETS_MANAGER_SECRET_JSON"
    )
    if explicit_json:
        secrets_payload = explicit_json
    else:
        if not region or not secret_id:
            return _maybe_skip_backend(
                app_env,
                "AWS Secrets Manager requires AWS_REGION and AWS_SECRETS_MANAGER_SECRET_ID",
            )
        client = boto3.client("secretsmanager", region_name=region)
        try:
            response = client.get_secret_value(SecretId=secret_id)
        except (BotoCoreError, ClientError) as exc:
            return _maybe_skip_backend(
                app_env, f"Failed to read AWS Secrets Manager secret: {exc}"
            )
        secrets_payload = response.get("SecretString")
        if not secrets_payload:
            return _maybe_skip_backend(
                app_env, "AWS Secrets Manager secret has no SecretString payload"
            )
    parsed = _parse_json_payload(secrets_payload, "AWS Secrets Manager")
    return _select_required_secrets(app_env, parsed)


def _load_from_ssm(app_env: str, config: dict[str, Any]) -> dict[str, Any]:
    region = config.get("aws_region")
    parameter_path = config.get("aws_ssm_parameter_path")
    if not region or not parameter_path:
        return _maybe_skip_backend(
            app_env, "AWS SSM requires AWS_REGION and AWS_SSM_PARAMETER_PATH"
        )
    client = boto3.client("ssm", region_name=region)
    try:
        paginator = client.get_paginator("get_parameters_by_path")
        secrets: dict[str, str] = {}
        for page in paginator.paginate(
            Path=parameter_path,
            WithDecryption=True,
            Recursive=True,
        ):
            for entry in page.get("Parameters", []):
                name = entry.get("Name", "")
                if not name:
                    continue
                key = name.split("/")[-1].upper()
                value = entry.get("Value")
                if value is not None:
                    secrets[key] = value
    except (BotoCoreError, ClientError) as exc:
        return _maybe_skip_backend(app_env, f"Failed to read AWS SSM parameters: {exc}")
    return _select_required_secrets(app_env, secrets)


def _select_required_secrets(app_env: str, secrets: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in REQUIRED_SECRET_KEYS:
        if key in secrets and secrets[key] is not None:
            normalized[key.lower()] = str(secrets[key])
    missing = [key for key in REQUIRED_SECRET_KEYS if key.lower() not in normalized]
    if missing and app_env in SECURE_ENVIRONMENTS:
        raise ValueError(f"Missing required secrets from backend: {', '.join(missing)}")
    if missing:
        logger.warning("Secrets backend missing required keys", extra={"missing": missing})
    return normalized


def _parse_json_payload(payload: str, source: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} secret payload is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{source} secret payload must be a JSON object")
    normalized: dict[str, Any] = {}
    for key, value in parsed.items():
        if isinstance(key, str):
            normalized[key.upper()] = value
    return normalized


def _maybe_skip_backend(app_env: str, message: str) -> dict[str, Any]:
    if app_env in DEV_DEFAULT_ENVIRONMENTS:
        logger.warning(message)
        return {}
    raise ValueError(message)
