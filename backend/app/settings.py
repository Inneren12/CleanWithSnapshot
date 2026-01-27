import json
import uuid
from ipaddress import ip_network
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "cleaning-economy-bot"
    cors_origins_raw: str | None = Field(None, validation_alias="cors_origins")
    app_env: Literal["dev", "prod"] = Field("prod")
    strict_cors: bool = Field(False)
    strict_policy_mode: bool = Field(False)
    admin_read_only: bool = Field(False)
    admin_ip_allowlist_cidrs_raw: str | None = Field(
        None, validation_alias="admin_ip_allowlist_cidrs"
    )
    redis_url: str | None = Field(None)
    rate_limit_per_minute: int = Field(30)
    admin_action_rate_limit_per_minute: int = Field(5)
    rate_limit_cleanup_minutes: int = Field(10)
    rate_limit_fail_open_seconds: int = Field(300)
    rate_limit_redis_probe_seconds: float = Field(5.0)
    time_overrun_reason_threshold: float = Field(1.2)
    break_glass_default_ttl_minutes: int = Field(30)
    break_glass_max_ttl_minutes: int = Field(60)
    trust_proxy_headers: bool = Field(False)
    trusted_proxy_ips_raw: str | None = Field(None, validation_alias="trusted_proxy_ips")
    trusted_proxy_cidrs_raw: str | None = Field(None, validation_alias="trusted_proxy_cidrs")
    pricing_config_path: str = Field("pricing/economy_v1.json")
    database_url: str = Field("postgresql+psycopg://postgres:postgres@postgres:5432/cleaning")
    database_pool_size: int = Field(
        5, ge=1, validation_alias=AliasChoices("DATABASE_POOL_SIZE", "database_pool_size")
    )
    database_max_overflow: int = Field(
        5, ge=0, validation_alias=AliasChoices("DATABASE_MAX_OVERFLOW", "database_max_overflow")
    )
    database_pool_timeout_seconds: float = Field(
        30.0,
        ge=0,
        validation_alias=AliasChoices(
            "DATABASE_POOL_TIMEOUT_SECONDS", "database_pool_timeout_seconds"
        ),
    )
    database_statement_timeout_ms: int = Field(
        5000,
        ge=0,
        validation_alias=AliasChoices(
            "DATABASE_STATEMENT_TIMEOUT_MS", "database_statement_timeout_ms"
        ),
    )
    email_mode: Literal["off", "sendgrid", "smtp"] = Field("off")
    email_from: str | None = Field(None)
    email_from_name: str | None = Field(None)
    sendgrid_api_key: str | None = Field(None)
    smtp_host: str | None = Field(None)
    smtp_port: int | None = Field(None)
    smtp_username: str | None = Field(None)
    smtp_password: str | None = Field(None)
    smtp_use_tls: bool = Field(True)
    sms_mode: Literal["off", "twilio"] = Field("off")
    call_mode: Literal["off", "twilio"] = Field("off")
    twilio_account_sid: str | None = Field(None)
    twilio_auth_token: str | None = Field(None)
    twilio_sms_from: str | None = Field(None)
    twilio_call_from: str | None = Field(None)
    twilio_call_url: str | None = Field(None)
    twilio_timeout_seconds: float = Field(10.0)
    dispatcher_alert_sms_to: str | None = Field(None)
    dispatcher_winter_months_raw: str = Field(
        "11,12,1,2,3", validation_alias="DISPATCHER_WINTER_MONTHS"
    )
    dispatcher_winter_travel_multiplier: float = Field(
        1.10, validation_alias="DISPATCHER_WINTER_TRAVEL_MULTIPLIER"
    )
    dispatcher_winter_buffer_min: int = Field(10, validation_alias="DISPATCHER_WINTER_BUFFER_MIN")
    dispatcher_downtown_parking_buffer_min: int = Field(
        15, validation_alias="DISPATCHER_DOWNTOWN_PARKING_BUFFER_MIN"
    )
    owner_basic_username: str | None = Field(None)
    owner_basic_password: str | None = Field(None)
    admin_basic_username: str | None = Field(None)
    admin_basic_password: str | None = Field(None)
    dispatcher_basic_username: str | None = Field(None)
    dispatcher_basic_password: str | None = Field(None)
    accountant_basic_username: str | None = Field(None)
    accountant_basic_password: str | None = Field(None)
    viewer_basic_username: str | None = Field(None)
    viewer_basic_password: str | None = Field(None)
    worker_basic_username: str | None = Field(None)
    worker_basic_password: str | None = Field(None)
    worker_team_id: int = Field(1)
    legacy_basic_auth_enabled: bool | None = Field(None)
    admin_mfa_required: bool = Field(False)
    admin_mfa_required_roles_raw: str | None = Field(None, validation_alias="admin_mfa_required_roles")
    admin_proxy_auth_enabled: bool = Field(False)
    admin_proxy_auth_required: bool = Field(False)
    admin_proxy_auth_header_user: str = Field("X-Admin-User")
    admin_proxy_auth_header_email: str = Field("X-Admin-Email")
    admin_proxy_auth_header_roles: str = Field("X-Admin-Roles")
    admin_proxy_auth_header_mfa: str = Field("X-Auth-MFA")
    admin_proxy_auth_secret: str | None = Field(None)
    auth_secret_key: str = Field("dev-auth-secret")
    auth_token_ttl_minutes: int = Field(60 * 24)
    auth_access_token_ttl_minutes: int = Field(
        15, validation_alias=AliasChoices("auth_access_token_ttl_minutes", "auth_token_ttl_minutes")
    )
    auth_refresh_token_ttl_minutes: int = Field(60 * 24 * 14)
    auth_session_ttl_minutes: int = Field(60 * 24)
    password_hash_scheme: Literal["argon2id", "bcrypt"] = Field("argon2id")
    password_hash_argon2_time_cost: int = Field(3)
    password_hash_argon2_memory_cost: int = Field(65536)
    password_hash_argon2_parallelism: int = Field(2)
    password_hash_bcrypt_cost: int = Field(12)
    session_ttl_minutes_worker: int = Field(60 * 12)
    session_ttl_minutes_client: int = Field(60 * 24 * 7)
    session_rotation_grace_minutes: int = Field(5)
    admin_notification_email: str | None = Field(None)
    public_base_url: str | None = Field(None)
    invoice_public_token_secret: str | None = Field(None)
    export_mode: Literal["off", "webhook", "sheets"] = Field("off")
    export_webhook_url: str | None = Field(None)
    export_webhook_timeout_seconds: int = Field(5)
    export_webhook_max_retries: int = Field(3)
    export_webhook_backoff_seconds: float = Field(1.0)
    export_webhook_allowed_hosts_raw: str | None = Field(None, validation_alias="export_webhook_allowed_hosts")
    export_webhook_allow_http: bool = Field(False)
    export_webhook_block_private_ips: bool = Field(True)
    data_export_signed_url_ttl_seconds: int = Field(600)
    data_export_retention_days: int = Field(7)
    data_export_request_rate_limit_per_minute: int = Field(1)
    data_export_request_rate_limit_per_hour: int = Field(5)
    data_export_download_rate_limit_per_minute: int = Field(10)
    data_export_download_failure_limit_per_window: int = Field(3)
    data_export_download_lockout_limit_per_window: int = Field(5)
    data_export_download_failure_window_seconds: int = Field(300)
    data_export_download_lockout_window_seconds: int = Field(1800)
    data_export_cooldown_minutes: int = Field(30)
    captcha_enabled: bool = Field(True)
    captcha_mode: Literal["off", "turnstile"] = Field("off")
    turnstile_secret_key: str | None = Field(None)
    google_maps_api_key: str | None = Field(None)
    maps_monthly_quota_limit: int = Field(10000)
    maps_requests_per_minute: int = Field(30)
    weather_traffic_mode: Literal["off", "open_meteo"] = Field("off")
    google_oauth_client_id: str | None = Field(None)
    google_oauth_client_secret: str | None = Field(None)
    google_oauth_redirect_uri: str | None = Field(None)
    quickbooks_oauth_client_id: str | None = Field(None)
    quickbooks_oauth_client_secret: str | None = Field(None)
    quickbooks_oauth_redirect_uri: str | None = Field(None)
    qbo_sync_interval_seconds: int = Field(1800)
    qbo_sync_initial_days: int = Field(30)
    qbo_sync_backfill_days: int = Field(7)
    gcal_sync_interval_seconds: int = Field(900)
    gcal_sync_initial_days: int = Field(30)
    gcal_sync_future_days: int = Field(30)
    gcal_sync_backfill_minutes: int = Field(60)
    retention_chat_days: int = Field(30)
    retention_lead_days: int = Field(365)
    retention_enable_leads: bool = Field(False)
    retention_application_log_days: int | None = Field(30)
    retention_analytics_event_days: int | None = Field(90)
    retention_soft_deleted_days: int | None = Field(30)
    retention_audit_log_days: int | None = Field(365 * 7)
    retention_batch_size: int = Field(500)
    soft_delete_purge_batch_size: int = Field(500)
    log_retention_batch_retries: int = Field(3)
    log_retention_batch_retry_delay_seconds: float = Field(0.5)
    audit_retention_admin_days: int = Field(365 * 3)
    audit_retention_config_days: int = Field(365 * 7)
    audit_retention_batch_size: int = Field(500)
    audit_retention_dry_run: bool = Field(False)
    feature_flag_max_horizon_days: int = Field(90)
    feature_flag_evaluation_throttle_minutes: int = Field(15)
    feature_flag_stale_inactive_days: int = Field(30)
    feature_flag_stale_max_evaluate_count: int = Field(1)
    feature_flag_expired_recent_days: int = Field(7)
    flag_retire_expired: bool = Field(True, validation_alias="FLAG_RETIRE_EXPIRED")
    flag_retire_stale_days: int | None = Field(90, validation_alias="FLAG_RETIRE_STALE_DAYS")
    flag_retire_dry_run: bool = Field(False, validation_alias="FLAG_RETIRE_DRY_RUN")
    flag_retire_recent_evaluation_days: int | None = Field(
        7, validation_alias="FLAG_RETIRE_RECENT_EVALUATION_DAYS"
    )
    chat_enabled: bool = Field(False)
    promos_enabled: bool = Field(False)
    default_worker_hourly_rate_cents: int = Field(2500)
    worker_alert_inactive_days: int = Field(30)
    worker_alert_rating_drop_threshold: float = Field(0.5)
    worker_alert_rating_drop_review_window: int = Field(3)
    worker_alert_skill_thresholds_raw: str | None = Field(
        None, validation_alias="worker_alert_skill_thresholds"
    )
    worker_skill_cert_requirements_raw: str | None = Field(
        None, validation_alias="worker_skill_cert_requirements"
    )
    client_risk_complaints_window_days: int = Field(90)
    client_risk_complaints_threshold: int = Field(3)
    client_risk_feedback_window_days: int = Field(90)
    client_risk_avg_rating_threshold: float = Field(3.0)
    client_risk_low_rating_threshold: int = Field(2)
    client_risk_low_rating_count_threshold: int = Field(2)
    client_churn_days_since_last_medium: int = Field(45)
    client_churn_days_since_last_high: int = Field(60)
    client_churn_avg_gap_multiplier_medium: float = Field(1.5)
    client_churn_avg_gap_multiplier_high: float = Field(2.0)
    client_churn_score_medium: int = Field(1)
    client_churn_score_high: int = Field(3)
    slot_provider_mode: Literal["stub", "db"] = Field("db")
    stripe_secret_key: str | None = Field(None)
    stripe_webhook_secret: str | None = Field(None)
    stripe_success_url: str = Field("http://localhost:3000/deposit-success?session_id={CHECKOUT_SESSION_ID}")
    stripe_cancel_url: str = Field("http://localhost:3000/deposit-cancelled")
    stripe_invoice_success_url: str = Field("http://localhost:3000/invoice-success?session_id={CHECKOUT_SESSION_ID}")
    stripe_invoice_cancel_url: str = Field("http://localhost:3000/invoice-cancelled")
    stripe_billing_success_url: str = Field("http://localhost:3000/billing/success?session_id={CHECKOUT_SESSION_ID}")
    stripe_billing_cancel_url: str = Field("http://localhost:3000/billing/cancelled")
    stripe_billing_portal_return_url: str = Field("http://localhost:3000/billing")
    stripe_circuit_failure_threshold: int = Field(5)
    stripe_circuit_recovery_seconds: float = Field(30.0)
    stripe_circuit_window_seconds: float = Field(60.0)
    stripe_circuit_half_open_max_calls: int = Field(2)
    client_portal_secret: str = Field("dev-client-portal-secret")
    worker_portal_secret: str | None = Field(None)
    client_portal_token_ttl_minutes: int = Field(30)
    client_portal_base_url: str | None = Field(None)
    deposit_percent: float = Field(0.25)
    deposit_currency: str = Field("cad")
    order_upload_root: str = Field("tmp")
    order_photo_max_bytes: int = Field(10 * 1024 * 1024)
    order_photo_allowed_mimes_raw: str = Field("image/jpeg,image/png,image/webp")
    storage_quota_reservation_ttl_seconds: int = Field(3600)
    storage_quota_cleanup_batch_size: int = Field(1000)
    order_storage_backend: Literal[
        "local",
        "s3",
        "memory",
        "r2",
        "cloudflare_r2",
        "cloudflare_images",
        "cf_images",
    ] = Field("local")
    order_photo_signed_url_ttl_seconds: int = Field(600)
    order_photo_signing_secret: str | None = Field(None)
    photo_url_ttl_seconds: int = Field(60, validation_alias="photo_url_ttl_seconds")
    photo_download_redirect_status: int = Field(302)
    photo_token_secret: str | None = Field(None)
    photo_token_bind_ua: bool = Field(True)
    photo_token_one_time: bool = Field(False)
    s3_endpoint: str | None = Field(None)
    s3_bucket: str | None = Field(None)
    s3_access_key: str | None = Field(None)
    s3_secret_key: str | None = Field(None)
    s3_region: str | None = Field(None)
    r2_endpoint: str | None = Field(None)
    r2_bucket: str | None = Field(None)
    r2_access_key: str | None = Field(None)
    r2_secret_key: str | None = Field(None)
    r2_region: str | None = Field("auto")
    r2_public_base_url: str | None = Field(None)
    cf_images_account_id: str | None = Field(None)
    cf_images_api_token: str | None = Field(None)
    cf_images_account_hash: str | None = Field(None)
    cf_images_default_variant: str = Field("public")
    cf_images_thumbnail_variant: str | None = Field(None)
    cf_images_signing_key: str | None = Field(None)
    s3_connect_timeout_seconds: float = Field(3.0)
    s3_read_timeout_seconds: float = Field(10.0)
    s3_max_attempts: int = Field(4)
    s3_circuit_failure_threshold: int = Field(4)
    s3_circuit_recovery_seconds: float = Field(20.0)
    s3_circuit_window_seconds: float = Field(60.0)
    storage_delete_retry_interval_seconds: int = Field(30)
    storage_delete_max_attempts: int = Field(5)
    storage_delete_batch_size: int = Field(50)
    testing: bool = Field(False)
    deposits_enabled: bool = Field(True)
    metrics_enabled: bool = Field(True)
    metrics_token: str | None = Field(None)
    jobs_enabled: bool = Field(False)
    job_runner_id: str | None = Field(None)
    job_heartbeat_required: bool = Field(False)
    job_heartbeat_ttl_seconds: int = Field(180)
    job_outbox_batch_size: int = Field(50)
    leads_nurture_runner_batch_size: int = Field(50)
    leads_nurture_runner_lookback_hours: int = Field(168)
    better_stack_heartbeat_url: str | None = Field(None)
    email_max_retries: int = Field(3)
    email_retry_backoff_seconds: float = Field(60.0)
    email_http_max_attempts: int = Field(3)
    email_http_backoff_seconds: float = Field(1.0)
    email_http_backoff_max_seconds: float = Field(8.0)
    email_timeout_seconds: float = Field(10.0)
    smtp_timeout_seconds: float = Field(10.0)
    email_circuit_failure_threshold: int = Field(5)
    email_circuit_recovery_seconds: float = Field(30.0)
    email_unsubscribe_secret: str | None = Field(None)
    email_unsubscribe_ttl_minutes: int = Field(7 * 24 * 60)
    nps_send_period_days: int = Field(30)
    email_temp_passwords: bool = Field(False)
    outbox_max_attempts: int = Field(5)
    outbox_base_backoff_seconds: float = Field(30.0)
    dlq_auto_replay_enabled: bool = Field(False)
    dlq_auto_replay_allow_outbox_kinds_raw: str | None = Field(
        None, validation_alias="dlq_auto_replay_allow_outbox_kinds"
    )
    dlq_auto_replay_allow_export_modes_raw: str | None = Field(
        None, validation_alias="dlq_auto_replay_allow_export_modes"
    )
    dlq_auto_replay_min_age_minutes: int = Field(60)
    dlq_auto_replay_max_per_org: int = Field(5)
    dlq_auto_replay_failure_streak_limit: int = Field(3)
    dlq_auto_replay_outbox_attempt_ceiling: int = Field(7)
    dlq_auto_replay_export_replay_limit: int = Field(2)
    dlq_auto_replay_export_cooldown_minutes: int = Field(120)
    default_org_id: uuid.UUID = Field(uuid.UUID("00000000-0000-0000-0000-000000000001"))

    model_config = SettingsConfigDict(env_file=".env", enable_decoding=False)

    @field_validator(
        "cors_origins_raw",
        "trusted_proxy_ips_raw",
        "trusted_proxy_cidrs_raw",
        "export_webhook_allowed_hosts_raw",
        "order_photo_allowed_mimes_raw",
        "dispatcher_winter_months_raw",
        mode="before",
    )
    @classmethod
    def normalize_list_raw(cls, value: object) -> str | None:
        return cls._normalize_raw_list(value)

    @field_validator("deposit_percent")
    @classmethod
    def validate_deposit_percent(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("deposit_percent must be between 0 and 1")
        return value

    @field_validator("time_overrun_reason_threshold")
    @classmethod
    def validate_time_threshold(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("time_overrun_reason_threshold must be positive")
        return value

    @field_validator("legacy_basic_auth_enabled", mode="before")
    @classmethod
    def normalize_legacy_basic_auth_enabled(cls, value: object) -> bool | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_prod_settings(self) -> "Settings":
        def _basic_auth_creds_configured() -> bool:
            return any(
                username and password
                for username, password in (
                    (self.owner_basic_username, self.owner_basic_password),
                    (self.admin_basic_username, self.admin_basic_password),
                    (self.dispatcher_basic_username, self.dispatcher_basic_password),
                    (self.accountant_basic_username, self.accountant_basic_password),
                    (self.viewer_basic_username, self.viewer_basic_password),
                )
            )

        if self.app_env != "prod":
            if self.testing:
                self.captcha_enabled = False
                self.captcha_mode = "off"
            if self.legacy_basic_auth_enabled is None:
                self.legacy_basic_auth_enabled = True
            if not self.captcha_enabled:
                self.captcha_mode = "off"
            return self

        if self.testing:
            raise ValueError("APP_ENV=prod disables testing mode and X-Test-Org overrides")

        if self.legacy_basic_auth_enabled is None:
            self.legacy_basic_auth_enabled = False

        if self.app_env == "prod" and self.legacy_basic_auth_enabled:
            if not _basic_auth_creds_configured():
                raise ValueError(
                    "APP_ENV=prod with LEGACY_BASIC_AUTH_ENABLED=true requires at least one Basic Auth username/password"
                )
            weak_passwords = {"change-me", "secret", "password", "admin", "123456", "qwerty"}

            def _is_weak(password: str) -> bool:
                normalized = password.strip()
                if len(normalized) < 12:
                    return True
                return normalized.lower() in weak_passwords

            for password in (
                self.owner_basic_password,
                self.admin_basic_password,
                self.dispatcher_basic_password,
                self.accountant_basic_password,
                self.viewer_basic_password,
            ):
                if password and _is_weak(password):
                    raise ValueError(
                        "APP_ENV=prod requires strong legacy Basic Auth passwords (min 12 chars, not a default placeholder)"
                    )

        def _require_secret(value: str | None, field_name: str, placeholders: set[str]) -> None:
            if value is None:
                raise ValueError(f"APP_ENV=prod requires {field_name} to be configured")
            normalized = value.strip()
            if not normalized or normalized in placeholders:
                raise ValueError(
                    f"APP_ENV=prod requires {field_name} to be set to a non-default value"
                )

        _require_secret(self.auth_secret_key, "AUTH_SECRET_KEY", {"dev-auth-secret"})
        _require_secret(
            self.client_portal_secret, "CLIENT_PORTAL_SECRET", {"dev-client-portal-secret"}
        )
        _require_secret(
            self.worker_portal_secret,
            "WORKER_PORTAL_SECRET",
            {"dev-worker-portal-secret"},
        )

        if self.strict_cors:
            if not self.cors_origins:
                raise ValueError("STRICT_CORS=true in prod requires explicit CORS_ORIGINS")
            if any(origin == "*" for origin in self.cors_origins):
                raise ValueError(
                    "STRICT_CORS=true in prod does not allow wildcard CORS_ORIGINS entries"
                )

        if self.metrics_enabled and (not self.metrics_token or not self.metrics_token.strip()):
            raise ValueError("METRICS_TOKEN is required when METRICS_ENABLED=true in prod")

        if self.admin_proxy_auth_required and not self.admin_proxy_auth_enabled:
            raise ValueError(
                "ADMIN_PROXY_AUTH_REQUIRED=true requires ADMIN_PROXY_AUTH_ENABLED=true"
            )

        if self.admin_proxy_auth_enabled:
            if not self.admin_proxy_auth_secret or not self.admin_proxy_auth_secret.strip():
                raise ValueError(
                    "ADMIN_PROXY_AUTH_SECRET is required when ADMIN_PROXY_AUTH_ENABLED=true in prod"
                )
            if len(self.admin_proxy_auth_secret.strip()) < 32:
                raise ValueError(
                    "ADMIN_PROXY_AUTH_SECRET must be at least 32 characters in prod"
                )

        if self.admin_ip_allowlist_cidrs_raw:
            for cidr in self.admin_ip_allowlist_cidrs:
                try:
                    ip_network(cidr, strict=False)
                except ValueError as exc:  # noqa: BLE001
                    raise ValueError(f"Invalid CIDR in ADMIN_IP_ALLOWLIST_CIDRS: {cidr}") from exc

        return self

    @property
    def cors_origins(self) -> list[str]:
        return self._parse_list(self.cors_origins_raw)

    @cors_origins.setter
    def cors_origins(self, value: list[str] | str | None) -> None:
        self.cors_origins_raw = self._normalize_raw_list(value)

    @property
    def trusted_proxy_ips(self) -> list[str]:
        return self._parse_list(self.trusted_proxy_ips_raw)

    @trusted_proxy_ips.setter
    def trusted_proxy_ips(self, value: list[str] | str | None) -> None:
        self.trusted_proxy_ips_raw = self._normalize_raw_list(value)

    @property
    def trusted_proxy_cidrs(self) -> list[str]:
        return self._parse_list(self.trusted_proxy_cidrs_raw)

    @trusted_proxy_cidrs.setter
    def trusted_proxy_cidrs(self, value: list[str] | str | None) -> None:
        self.trusted_proxy_cidrs_raw = self._normalize_raw_list(value)

    @property
    def export_webhook_allowed_hosts(self) -> list[str]:
        return self._parse_list(self.export_webhook_allowed_hosts_raw)

    @export_webhook_allowed_hosts.setter
    def export_webhook_allowed_hosts(self, value: list[str] | str | None) -> None:
        self.export_webhook_allowed_hosts_raw = self._normalize_raw_list(value)

    @property
    def admin_ip_allowlist_cidrs(self) -> list[str]:
        return self._parse_list(self.admin_ip_allowlist_cidrs_raw)

    @admin_ip_allowlist_cidrs.setter
    def admin_ip_allowlist_cidrs(self, value: list[str] | str | None) -> None:
        self.admin_ip_allowlist_cidrs_raw = self._normalize_raw_list(value)

    @property
    def admin_mfa_required_roles(self) -> list[str]:
        parsed = self._parse_list(self.admin_mfa_required_roles_raw)
        return parsed or ["owner", "admin"]

    @admin_mfa_required_roles.setter
    def admin_mfa_required_roles(self, value: list[str] | str | None) -> None:
        self.admin_mfa_required_roles_raw = self._normalize_raw_list(value)

    @property
    def dispatcher_winter_months(self) -> list[int]:
        parsed = self._parse_list(self.dispatcher_winter_months_raw)
        months: list[int] = []
        for entry in parsed:
            try:
                value = int(entry)
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 12:
                months.append(value)
        return months

    @dispatcher_winter_months.setter
    def dispatcher_winter_months(self, value: list[int] | str | None) -> None:
        self.dispatcher_winter_months_raw = self._normalize_raw_list(value)

    @property
    def dlq_auto_replay_allow_outbox_kinds(self) -> list[str]:
        return self._parse_list(self.dlq_auto_replay_allow_outbox_kinds_raw)

    @dlq_auto_replay_allow_outbox_kinds.setter
    def dlq_auto_replay_allow_outbox_kinds(self, value: list[str] | str | None) -> None:
        self.dlq_auto_replay_allow_outbox_kinds_raw = self._normalize_raw_list(value)

    @property
    def dlq_auto_replay_allow_export_modes(self) -> list[str]:
        return self._parse_list(self.dlq_auto_replay_allow_export_modes_raw)

    @dlq_auto_replay_allow_export_modes.setter
    def dlq_auto_replay_allow_export_modes(self, value: list[str] | str | None) -> None:
        self.dlq_auto_replay_allow_export_modes_raw = self._normalize_raw_list(value)

    @property
    def worker_alert_skill_thresholds(self) -> dict[str, dict[str, object]]:
        raw = self.worker_alert_skill_thresholds_raw
        if raw is None:
            return {}
        stripped = raw.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        normalized: dict[str, dict[str, object]] = {}
        for key, value in parsed.items():
            if not isinstance(key, str):
                continue
            if not isinstance(value, dict):
                continue
            normalized[key.strip().lower()] = value
        return normalized

    @property
    def email_sender(self) -> str | None:
        return self.email_from

    @email_sender.setter
    def email_sender(self, value: str | None) -> None:
        self.email_from = value

    @staticmethod
    def _normalize_raw_list(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return json.dumps(value)
        return str(value)

    @staticmethod
    def _parse_list(raw: str | None) -> list[str]:
        if raw is None:
            return []
        stripped = raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(entry).strip() for entry in parsed if str(entry).strip()]
            return [str(parsed).strip()] if str(parsed).strip() else []
        entries = [entry.strip() for entry in stripped.split(",")]
        return [entry for entry in entries if entry]

    @property
    def order_photo_allowed_mimes(self) -> list[str]:
        parsed = self._parse_list(self.order_photo_allowed_mimes_raw)
        if parsed:
            return parsed
        return ["image/jpeg", "image/png", "image/webp"]


settings = Settings()
