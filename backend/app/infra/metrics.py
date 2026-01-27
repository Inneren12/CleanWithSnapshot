import logging
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)


class Metrics:
    def __init__(self, enabled: bool = False, *, service_name: str | None = None) -> None:
        self._configure(enabled, service_name=service_name)

    def _configure(self, enabled: bool, *, service_name: str | None = None) -> None:
        self.enabled = enabled
        self.service_name = service_name or "unknown"
        self.registry = CollectorRegistry(auto_describe=True)
        if not enabled:
            self.outbox_queue_depth = None
            self.stripe_webhook_events = None
            self.stripe_webhook_circuit_open = None
            self.email_adapter_outcomes = None
            self.webhook_events = None
            self.webhook_errors = None
            self.email_jobs = None
            self.email_notifications = None
            self.email_dlq = None
            self.dlq_replay = None
            self.dlq_depth_snapshot = None
            self.bookings = None
            self.http_5xx = None
            self.http_requests = None
            self.http_latency = None
            self.job_heartbeat = None
            self.job_heartbeat_age = None
            self.job_last_success = None
            self.jobs_last_success = None
            self.jobs_run_total = None
            self.jobs_duration = None
            self.job_runner_up = None
            self.job_errors = None
            self.outbox_pending_total = None
            self.outbox_deliver_total = None
            self.outbox_lag_seconds = None
            self.circuit_state = None
            self.org_user_quota_rejections = None
            self.org_active_bookings_quota_rejections = None
            self.org_storage_quota_rejections = None
            self.org_rate_limit_blocks = None
            self.http_429_total = None
            self.auth_failures_total = None
            self.admin_auth_events_total = None
            self.admin_auth_success_total = None
            self.admin_auth_failure_total = None
            self.admin_break_glass_total = None
            self.data_export_rate_limited_total = None
            self.data_export_denied_total = None
            self.outbox_failures_total = None
            self.storage_bytes_used = None
            self.storage_reservations_pending = None
            self.audit_records_purged_total = None
            self.audit_records_on_legal_hold_total = None
            self.logs_purged_total = None
            self.retention_records_deleted_total = None
            self.analytics_events_purged_total = None
            self.soft_deleted_entities_purged_total = None
            self.feature_flags_stale_total = None
            self.break_glass_grants_total = None
            self.break_glass_active = None
            return

        self.webhook_events = Counter(
            "webhook_events_total",
            "Webhook events processed by result.",
            ["result"],
            registry=self.registry,
        )
        self.stripe_webhook_events = Counter(
            "stripe_webhook_events_total",
            "Stripe webhook outcomes by result.",
            ["outcome"],
            registry=self.registry,
        )
        self.webhook_errors = Counter(
            "webhook_errors_total",
            "Webhook errors by type (low cardinality).",
            ["type"],
            registry=self.registry,
        )
        self.stripe_webhook_circuit_open = Counter(
            "stripe_webhook_circuit_open_total",
            "Stripe webhook circuit breaker opened.",
            registry=self.registry,
        )
        self.email_jobs = Counter(
            "email_jobs_total",
            "Email job outcomes per job name.",
            ["job", "status"],
            registry=self.registry,
        )
        self.email_notifications = Counter(
            "email_notifications_total",
            "Email delivery attempts by template and status.",
            ["template", "status"],
            registry=self.registry,
        )
        self.dlq_replay = Counter(
            "dlq_replay_total",
            "DLQ auto replay attempts and outcomes by kind and org.",
            ["kind", "status", "org"],
            registry=self.registry,
        )
        self.email_adapter_outcomes = Counter(
            "email_adapter_outcomes_total",
            "Email adapter send outcomes.",
            ["status"],
            registry=self.registry,
        )
        self.email_dlq = Gauge(
            "email_dlq_messages",
            "Email dead-letter queue depth by status.",
            ["status"],
            registry=self.registry,
        )
        self.dlq_depth_snapshot = Gauge(
            "dlq_depth_snapshot",
            "Snapshot of DLQ depth before/after auto replay.",
            ["kind", "stage"],
            registry=self.registry,
        )
        self.outbox_queue_depth = Gauge(
            "outbox_queue_messages",
            "Outbox queue depth by status (pending/retry/dead).",
            ["status"],
            registry=self.registry,
        )
        self.bookings = Counter(
            "bookings_total",
            "Booking lifecycle events.",
            ["action"],
            registry=self.registry,
        )
        self.http_5xx = Counter(
            "http_5xx_total",
            "HTTP responses with status >= 500.",
            ["method", "route", "service"],
            registry=self.registry,
        )
        self.http_requests = Counter(
            "http_requests_total",
            "HTTP requests by method, route, and status class.",
            ["method", "route", "status_class", "service"],
            registry=self.registry,
        )
        self.http_latency = Histogram(
            "http_request_latency_seconds",
            "HTTP request latency in seconds.",
            ["method", "route", "status_class", "service"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=self.registry,
        )
        self.job_heartbeat = Gauge(
            "job_last_heartbeat_timestamp",
            "Unix timestamp for the latest job heartbeat.",
            ["job"],
            registry=self.registry,
        )
        self.job_heartbeat_age = Gauge(
            "job_heartbeat_age_seconds",
            "Age of the latest job heartbeat in seconds.",
            ["job"],
            registry=self.registry,
        )
        self.job_last_success = Gauge(
            "job_last_success_timestamp",
            "Unix timestamp for the latest successful job loop.",
            ["job"],
            registry=self.registry,
        )
        self.jobs_last_success = Gauge(
            "jobs_last_success_timestamp",
            "Unix timestamp for the latest successful job run.",
            ["job"],
            registry=self.registry,
        )
        self.jobs_run_total = Counter(
            "jobs_run_total",
            "Job run outcomes by job name.",
            ["job", "result"],
            registry=self.registry,
        )
        self.jobs_duration = Histogram(
            "jobs_duration_seconds",
            "Job run duration in seconds.",
            ["job"],
            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )
        self.job_runner_up = Gauge(
            "job_runner_up",
            "Job runner liveness indicator (1=recent heartbeat).",
            ["job"],
            registry=self.registry,
        )
        self.job_errors = Counter(
            "job_errors_total",
            "Job execution errors by job and reason.",
            ["job", "reason"],
            registry=self.registry,
        )
        self.outbox_pending_total = Gauge(
            "outbox_pending_total",
            "Outbox pending messages by type.",
            ["type"],
            registry=self.registry,
        )
        self.storage_bytes_used = Gauge(
            "storage_bytes_used",
            "Total storage bytes used across orgs.",
            registry=self.registry,
        )
        self.storage_reservations_pending = Gauge(
            "storage_reservations_pending",
            "Count of pending storage reservations.",
            registry=self.registry,
        )
        self.outbox_deliver_total = Counter(
            "outbox_deliver_total",
            "Outbox delivery attempts by type and result.",
            ["type", "result"],
            registry=self.registry,
        )
        self.outbox_failures_total = Counter(
            "outbox_failures_total",
            "Outbox delivery failures by type.",
            ["type"],
            registry=self.registry,
        )
        self.outbox_lag_seconds = Gauge(
            "outbox_lag_seconds",
            "Age of the oldest pending outbox event by type.",
            ["type"],
            registry=self.registry,
        )
        self.audit_records_purged_total = Counter(
            "audit_records_purged_total",
            "Audit records purged by retention job.",
            registry=self.registry,
        )
        self.audit_records_on_legal_hold_total = Counter(
            "audit_records_on_legal_hold_total",
            "Audit records prevented from purge due to legal hold.",
            registry=self.registry,
        )
        self.logs_purged_total = Counter(
            "logs_purged_total",
            "Application logs purged by retention job.",
            registry=self.registry,
        )
        self.retention_records_deleted_total = Counter(
            "retention_records_deleted_total",
            "Records deleted by data retention category.",
            ["category"],
            registry=self.registry,
        )
        self.analytics_events_purged_total = Counter(
            "analytics_events_purged_total",
            "Raw analytics events purged by retention job.",
            registry=self.registry,
        )
        self.soft_deleted_entities_purged_total = Counter(
            "soft_deleted_entities_purged_total",
            "Soft-deleted entities purged after grace period.",
            ["entity_type"],
            registry=self.registry,
        )
        self.feature_flags_stale_total = Gauge(
            "feature_flags_stale_total",
            "Count of stale or policy-mismatched feature flags by category.",
            ["category"],
            registry=self.registry,
        )
        self.break_glass_grants_total = Counter(
            "break_glass_grants_total",
            "Break-glass grant events by scope and event type.",
            ["scope", "event"],
            registry=self.registry,
        )
        self.break_glass_active = Gauge(
            "break_glass_active",
            "Active break-glass grants currently in effect.",
            registry=self.registry,
        )
        self.circuit_state = Gauge(
            "circuit_state",
            "Circuit breaker state (0=closed, 0.5=half-open, 1=open).",
            ["circuit"],
            registry=self.registry,
        )
        self.org_user_quota_rejections = Counter(
            "org_user_quota_rejections_total",
            "Organization user quota rejections.",
            ["reason"],
            registry=self.registry,
        )
        self.org_active_bookings_quota_rejections = Counter(
            "org_active_bookings_quota_rejections_total",
            "Organization booking quota rejections.",
            ["reason"],
            registry=self.registry,
        )
        self.org_storage_quota_rejections = Counter(
            "org_storage_quota_rejections_total",
            "Organization storage quota rejections.",
            ["reason"],
            registry=self.registry,
        )
        self.org_rate_limit_blocks = Counter(
            "org_rate_limit_blocks_total",
            "Rate limit blocks by request bucket.",
            ["bucket"],
            registry=self.registry,
        )
        self.http_429_total = Counter(
            "http_429_total",
            "HTTP 429 responses by bucket.",
            ["bucket"],
            registry=self.registry,
        )
        self.auth_failures_total = Counter(
            "auth_failures_total",
            "Authentication failures by source and reason.",
            ["source", "reason"],
            registry=self.registry,
        )
        self.admin_auth_events_total = Counter(
            "admin_auth_events_total",
            "Admin authentication attempts by outcome, method, MFA, and failure reason.",
            ["outcome", "method", "mfa", "reason"],
            registry=self.registry,
        )
        self.admin_auth_success_total = Counter(
            "admin_auth_success_total",
            "Admin authentication successes by method, MFA, and source CIDR.",
            ["method", "mfa", "source_cidr"],
            registry=self.registry,
        )
        self.admin_auth_failure_total = Counter(
            "admin_auth_failure_total",
            "Admin authentication failures by method, reason, and source CIDR.",
            ["method", "reason", "source_cidr"],
            registry=self.registry,
        )
        self.admin_break_glass_total = Counter(
            "admin_break_glass_total",
            "Admin authentication attempts using break-glass access.",
            registry=self.registry,
        )
        self.data_export_rate_limited_total = Counter(
            "data_export_rate_limited_total",
            "Data export rate limits by endpoint.",
            ["endpoint"],
            registry=self.registry,
        )
        self.data_export_denied_total = Counter(
            "data_export_denied_total",
            "Data export denied attempts by reason.",
            ["reason"],
            registry=self.registry,
        )

    def record_webhook(self, result: str) -> None:
        if not self.enabled or self.webhook_events is None:
            return
        self.webhook_events.labels(result=result).inc()

    def record_stripe_webhook(self, outcome: str) -> None:
        if not self.enabled or self.stripe_webhook_events is None:
            return
        safe_outcome = outcome or "unknown"
        self.stripe_webhook_events.labels(outcome=safe_outcome).inc()

    def record_webhook_error(self, error_type: str) -> None:
        if not self.enabled or self.webhook_errors is None:
            return
        safe_type = error_type or "unknown"
        self.webhook_errors.labels(type=safe_type).inc()

    def record_stripe_circuit_open(self) -> None:
        if not self.enabled or self.stripe_webhook_circuit_open is None:
            return
        self.stripe_webhook_circuit_open.inc()

    def record_email_job(self, job: str, status: str, count: int = 1) -> None:
        if not self.enabled or self.email_jobs is None:
            return
        if count <= 0:
            return
        self.email_jobs.labels(job=job, status=status).inc(count)

    def record_email_adapter(self, status: str) -> None:
        if not self.enabled or self.email_adapter_outcomes is None:
            return
        safe_status = status or "unknown"
        self.email_adapter_outcomes.labels(status=safe_status).inc()

    def record_booking(self, action: str, count: int = 1) -> None:
        if not self.enabled or self.bookings is None:
            return
        if count <= 0:
            return
        self.bookings.labels(action=action).inc(count)

    def record_http_5xx(self, method: str, route: str) -> None:
        if not self.enabled or self.http_5xx is None:
            return
        self.http_5xx.labels(method=method, route=route, service=self.service_name).inc()

    def record_http_latency(
        self, method: str, route: str, status_code: int, duration_seconds: float
    ) -> None:
        if not self.enabled or self.http_latency is None:
            return
        status_class = f"{status_code // 100}xx" if status_code else "unknown"
        duration_seconds = max(0.0, float(duration_seconds))
        self.http_latency.labels(
            method=method, route=route, status_class=status_class, service=self.service_name
        ).observe(duration_seconds)

    def record_http_request(self, method: str, route: str, status_code: int) -> None:
        if not self.enabled or self.http_requests is None:
            return
        status_class = f"{status_code // 100}xx" if status_code else "unknown"
        self.http_requests.labels(
            method=method, route=route, status_class=status_class, service=self.service_name
        ).inc()

    def record_job_heartbeat(self, job: str, timestamp: float | None = None) -> None:
        if not self.enabled or self.job_heartbeat is None or self.job_runner_up is None:
            return
        ts = timestamp if timestamp is not None else time.time()
        self.job_heartbeat.labels(job=job).set(ts)
        self.job_runner_up.labels(job=job).set(1)

    def record_job_heartbeat_age(
        self, job: str, age_seconds: float, *, threshold_seconds: float | None = None
    ) -> None:
        if (
            not self.enabled
            or self.job_heartbeat_age is None
            or self.job_runner_up is None
        ):
            return
        safe_age = max(0.0, float(age_seconds))
        self.job_heartbeat_age.labels(job=job).set(safe_age)
        if threshold_seconds is not None:
            self.job_runner_up.labels(job=job).set(1 if safe_age <= threshold_seconds else 0)

    def record_job_success(self, job: str, timestamp: float | None = None) -> None:
        if (
            not self.enabled
            or self.job_last_success is None
            or self.jobs_last_success is None
        ):
            return
        ts = timestamp if timestamp is not None else time.time()
        self.job_last_success.labels(job=job).set(ts)
        self.jobs_last_success.labels(job=job).set(ts)

    def record_job_error(self, job: str, reason: str) -> None:
        if not self.enabled or self.job_errors is None:
            return
        safe_reason = reason or "unknown"
        self.job_errors.labels(job=job, reason=safe_reason).inc()

    def record_job_run(self, job: str, result: str) -> None:
        if not self.enabled or self.jobs_run_total is None:
            return
        safe_result = result or "unknown"
        self.jobs_run_total.labels(job=job, result=safe_result).inc()

    def record_job_duration(self, job: str, duration_seconds: float) -> None:
        if not self.enabled or self.jobs_duration is None:
            return
        safe_duration = max(0.0, float(duration_seconds))
        self.jobs_duration.labels(job=job).observe(safe_duration)

    def record_email_notification(self, template: str, status: str, count: int = 1) -> None:
        if not self.enabled or self.email_notifications is None:
            return
        if count <= 0:
            return
        safe_template = template or "unknown"
        self.email_notifications.labels(template=safe_template, status=status).inc(count)

    def set_email_dlq_depth(self, status: str, count: int) -> None:
        if not self.enabled or self.email_dlq is None:
            return
        self.email_dlq.labels(status=status).set(max(0, count))

    def set_outbox_depth(self, status: str, count: int) -> None:
        if not self.enabled or self.outbox_queue_depth is None:
            return
        safe_status = status or "unknown"
        self.outbox_queue_depth.labels(status=safe_status).set(max(0, count))

    def set_outbox_pending_total(self, kind: str, count: int) -> None:
        if not self.enabled or self.outbox_pending_total is None:
            return
        safe_kind = kind or "unknown"
        self.outbox_pending_total.labels(type=safe_kind).set(max(0, count))

    def record_outbox_delivery(self, kind: str, result: str) -> None:
        if not self.enabled or self.outbox_deliver_total is None:
            return
        safe_kind = kind or "unknown"
        safe_result = result or "unknown"
        self.outbox_deliver_total.labels(type=safe_kind, result=safe_result).inc()
        if safe_result == "error" and self.outbox_failures_total is not None:
            self.outbox_failures_total.labels(type=safe_kind).inc()

    def record_org_user_quota_rejection(self, reason: str) -> None:
        if not self.enabled or self.org_user_quota_rejections is None:
            return
        safe_reason = reason or "unknown"
        self.org_user_quota_rejections.labels(reason=safe_reason).inc()

    def record_org_active_bookings_quota_rejection(self, reason: str) -> None:
        if not self.enabled or self.org_active_bookings_quota_rejections is None:
            return
        safe_reason = reason or "unknown"
        self.org_active_bookings_quota_rejections.labels(reason=safe_reason).inc()

    def record_org_storage_quota_rejection(self, reason: str) -> None:
        if not self.enabled or self.org_storage_quota_rejections is None:
            return
        safe_reason = reason or "unknown"
        self.org_storage_quota_rejections.labels(reason=safe_reason).inc()

    def record_rate_limit_block(self, bucket: str) -> None:
        if not self.enabled or self.org_rate_limit_blocks is None:
            return
        safe_bucket = bucket or "unknown"
        self.org_rate_limit_blocks.labels(bucket=safe_bucket).inc()

    def record_http_429(self, bucket: str) -> None:
        if not self.enabled or self.http_429_total is None:
            return
        safe_bucket = bucket or "unknown"
        self.http_429_total.labels(bucket=safe_bucket).inc()

    def record_auth_failure(self, source: str, reason: str) -> None:
        if not self.enabled or self.auth_failures_total is None:
            return
        safe_source = source or "unknown"
        safe_reason = reason or "unknown"
        self.auth_failures_total.labels(source=safe_source, reason=safe_reason).inc()

    def record_admin_auth_event(
        self,
        *,
        outcome: str | None,
        method: str | None,
        mfa: bool | None,
        reason: str | None,
    ) -> None:
        if not self.enabled or self.admin_auth_events_total is None:
            return
        safe_outcome = outcome or "unknown"
        safe_method = method or "unknown"
        safe_mfa = "unknown" if mfa is None else ("true" if mfa else "false")
        safe_reason = reason or "none"
        self.admin_auth_events_total.labels(
            outcome=safe_outcome,
            method=safe_method,
            mfa=safe_mfa,
            reason=safe_reason,
        ).inc()

    def record_admin_auth_success(
        self,
        *,
        method: str | None,
        mfa: bool | None,
        source_cidr: str | None,
    ) -> None:
        if not self.enabled or self.admin_auth_success_total is None:
            return
        safe_method = method or "unknown"
        safe_mfa = "unknown" if mfa is None else ("true" if mfa else "false")
        safe_cidr = source_cidr or "unknown"
        self.admin_auth_success_total.labels(
            method=safe_method,
            mfa=safe_mfa,
            source_cidr=safe_cidr,
        ).inc()

    def record_admin_auth_failure(
        self,
        *,
        method: str | None,
        reason: str | None,
        source_cidr: str | None,
    ) -> None:
        if not self.enabled or self.admin_auth_failure_total is None:
            return
        safe_method = method or "unknown"
        safe_reason = reason or "unknown"
        safe_cidr = source_cidr or "unknown"
        self.admin_auth_failure_total.labels(
            method=safe_method,
            reason=safe_reason,
            source_cidr=safe_cidr,
        ).inc()

    def record_admin_break_glass(self) -> None:
        if not self.enabled or self.admin_break_glass_total is None:
            return
        self.admin_break_glass_total.inc()

    def record_data_export_rate_limited(self, endpoint: str) -> None:
        if not self.enabled or self.data_export_rate_limited_total is None:
            return
        safe_endpoint = endpoint or "unknown"
        self.data_export_rate_limited_total.labels(endpoint=safe_endpoint).inc()

    def record_data_export_denied(self, reason: str) -> None:
        if not self.enabled or self.data_export_denied_total is None:
            return
        safe_reason = reason or "unknown"
        self.data_export_denied_total.labels(reason=safe_reason).inc()

    def record_audit_purge(self, count: int) -> None:
        if not self.enabled or self.audit_records_purged_total is None:
            return
        if count <= 0:
            return
        self.audit_records_purged_total.inc(count)

    def record_audit_legal_hold(self, count: int) -> None:
        if not self.enabled or self.audit_records_on_legal_hold_total is None:
            return
        if count <= 0:
            return
        self.audit_records_on_legal_hold_total.inc(count)

    def record_logs_purged(self, count: int) -> None:
        if not self.enabled or self.logs_purged_total is None:
            return
        if count <= 0:
            return
        self.logs_purged_total.inc(count)

    def record_retention_deletion(self, category: str, count: int) -> None:
        if not self.enabled or self.retention_records_deleted_total is None:
            return
        if count <= 0:
            return
        safe_category = category or "unknown"
        self.retention_records_deleted_total.labels(category=safe_category).inc(count)

    def record_analytics_events_purged(self, count: int) -> None:
        if not self.enabled or self.analytics_events_purged_total is None:
            return
        if count <= 0:
            return
        self.analytics_events_purged_total.inc(count)

    def record_soft_delete_purge(self, entity_type: str, count: int) -> None:
        if not self.enabled or self.soft_deleted_entities_purged_total is None:
            return
        if count <= 0:
            return
        safe_type = entity_type or "unknown"
        self.soft_deleted_entities_purged_total.labels(entity_type=safe_type).inc(count)

    def record_storage_quota_rejection(self, reason: str) -> None:
        self.record_org_storage_quota_rejection(reason)

    def record_booking_quota_rejection(self, reason: str) -> None:
        self.record_org_active_bookings_quota_rejection(reason)

    def set_storage_bytes_used(self, total_bytes: int) -> None:
        if not self.enabled or self.storage_bytes_used is None:
            return
        self.storage_bytes_used.set(max(0, int(total_bytes)))

    def set_storage_reservations_pending(self, count: int) -> None:
        if not self.enabled or self.storage_reservations_pending is None:
            return
        self.storage_reservations_pending.set(max(0, int(count)))

    def set_outbox_lag(self, kind: str, lag_seconds: float) -> None:
        if not self.enabled or self.outbox_lag_seconds is None:
            return
        safe_kind = kind or "unknown"
        safe_lag = max(0.0, float(lag_seconds))
        self.outbox_lag_seconds.labels(type=safe_kind).set(safe_lag)

    def record_dlq_depth(self, kind: str, stage: str, count: int) -> None:
        if not self.enabled or self.dlq_depth_snapshot is None:
            return
        safe_kind = kind or "unknown"
        safe_stage = stage or "unknown"
        self.dlq_depth_snapshot.labels(kind=safe_kind, stage=safe_stage).set(max(0, count))

    def record_dlq_replay(self, kind: str, status: str, org: str) -> None:
        if not self.enabled or self.dlq_replay is None:
            return
        safe_kind = kind or "unknown"
        safe_status = status or "unknown"
        safe_org = org or "unknown"
        self.dlq_replay.labels(kind=safe_kind, status=safe_status, org=safe_org).inc()

    def record_circuit_state(self, circuit: str, state: str) -> None:
        if not self.enabled or self.circuit_state is None:
            return
        value = {"closed": 0, "half_open": 0.5, "open": 1}.get(state, -1)
        self.circuit_state.labels(circuit=circuit).set(value)

    def record_feature_flag_stale_counts(self, counts: dict[str, int]) -> None:
        if not self.enabled or self.feature_flags_stale_total is None:
            return
        for category, value in counts.items():
            safe_category = category or "unknown"
            self.feature_flags_stale_total.labels(category=safe_category).set(max(0, int(value)))

    def record_break_glass_grant(self, scope: str, event: str) -> None:
        if not self.enabled or self.break_glass_grants_total is None:
            return
        safe_scope = scope or "unknown"
        safe_event = event or "unknown"
        self.break_glass_grants_total.labels(scope=safe_scope, event=safe_event).inc()

    def set_break_glass_active(self, count: int) -> None:
        if not self.enabled or self.break_glass_active is None:
            return
        self.break_glass_active.set(max(0, int(count)))

    def render(self) -> tuple[bytes, str]:
        if not self.enabled:
            return b"metrics_disabled 1\n", "text/plain; version=0.0.4"
        try:
            return generate_latest(self.registry), CONTENT_TYPE_LATEST
        except Exception:  # noqa: BLE001
            logger.exception("metrics_render_failed")
            return b"metrics_render_failed 1\n", "text/plain; version=0.0.4"


metrics = Metrics(enabled=False)


def configure_metrics(enabled: bool, service_name: str | None = None) -> Metrics:
    metrics._configure(enabled, service_name=service_name)
    return metrics
