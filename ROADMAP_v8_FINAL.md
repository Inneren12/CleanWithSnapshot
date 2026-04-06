# Summa Vision — Production Roadmap v8.0 (Final)

**Статус:** Финальная версия. Прошла 4 раунда архитектурного review.
**Цель:** Market-entry MVP enterprise-grade качества.
**Команда:** 1 founder-developer + AI agents.
**Целевой timeline:** ~7 недель до первого revenue.

---

## Содержание

1. [Архитектурные решения (R1–R21)](#архитектурные-решения)
2. [Prerequisites Checklist](#prerequisites-checklist)
3. [Порядок этапов](#порядок-этапов)
4. [Этап 0: Infrastructure Foundation](#этап-0-infrastructure-foundation)
5. [Этап A: Data Engine](#этап-a-data-engine)
6. [Этап B: Visual Engine](#этап-b-visual-engine)
7. [Этап D: Public Site + Revenue](#этап-d-public-site--revenue)
8. [Этап C: Admin UI](#этап-c-admin-ui)
9. [Бэклог](#бэклог)
10. [CI/CD Gate Policy](#cicd-gate-policy)
11. [Secret Management Policy](#secret-management-policy)
12. [Deploy Compatibility Rules](#deploy-compatibility-rules)
13. [S3 Key Naming Convention](#s3-key-naming-convention)
14. [Event Taxonomy](#event-taxonomy)
15. [Definition of Done](#definition-of-done)

---

## Архитектурные решения

Каждое решение имеет уникальный ID. Промты для агентов ссылаются на эти ID.

### R1: Приватный S3, CDN, безопасные Magic Links

- S3 bucket: Block All Public Access. Lowres доступны ТОЛЬКО через CDN.
- `CDN_BASE_URL` — обязательная env variable. Dev: `http://localhost:9000/summa-vision-dev/lowres`. Prod: `https://cdn.summa.vision`.
- Gallery API возвращает `cdn_url = f"{settings.cdn_base_url}/{s3_key}"`. Никогда presigned URL для gallery.
- Presigned URL — ТОЛЬКО для highres ZIP после token exchange. TTL = 10 min.
- В email отправляется Magic Link на фронтенд, НЕ presigned URL.
- Фронтенд: raw token очищается из URL через `history.replaceState()` сразу после чтения.
- Final download — ТОЛЬКО через `window.location.assign(url)`, НИКОГДА через `fetch()`.

### R2: Ресурсные семафоры

- `app.state.data_sem = asyncio.Semaphore(2)` — CPU/RAM transforms (Polars, PyArrow).
- `app.state.render_sem = asyncio.Semaphore(2)` — render/composite (CairoSVG, Pillow).
- `app.state.io_sem = asyncio.Semaphore(10)` — network/file I/O (boto3, httpx).
- Все синхронные тяжёлые вызовы — через `await run_in_threadpool(fn, *args)`.
- Правило: network fetch → io_sem; parse/join/aggregate → data_sem.

### R3: Zero-CSV Policy

- Внутреннее хранилище processed data — ТОЛЬКО Parquet.
- CSV допустим ТОЛЬКО как внешний экспорт для пользователя внутри ZIP.

### R4: Polars-first с явной Pandas boundary

**Polars** — основной dataframe engine. **PyArrow** — обязательная зависимость.

Явная граница:

| Зона | Файлы | Engine | Правило |
|------|-------|--------|---------|
| LEGACY | `services/statcan/service.py`, `schemas.py`, `client.py` | Pandas | Не трогать без отдельного PR |
| NEW | `services/statcan/data_fetch.py`, `catalog_sync.py`, `services/data/workbench.py`, `services/graphics/pipeline.py` | Polars | Pandas import запрещён |
| BRIDGE | `data_fetch.py` после CSV download | Polars | Одна точка конвертации: CSV bytes → `pl.read_csv()`. Legacy `normalize_dataset()` НЕ вызывается. Новая Polars-native normalization. |

Запрещённые Pandas-only idioms в Polars-path: `df.duplicated()`, `df.astype(object)`, `df.replace({pd.NA: None})`.

### R5: Polars CPU Guard

```
ENV POLARS_MAX_THREADS=2
```

Обязательно в Dockerfile. Предотвращает thread starvation и CPU thrashing.

### R6: Короткоживущие DB sessions

- Тяжёлые операции НЕ удерживают DB session.
- Pattern: open session → read metadata → close → heavy work → open session → write result.
- AsyncEngine: `pool_size=8, max_overflow=8, pool_pre_ping=True`.

### R7: Persistent DB-backed Job Manager

- In-memory TaskManager не используется как source of truth.
- Таблица `Job` с persistent state.
- Job history переживает рестарты.
- UI и API читают jobs из БД.

### R8: SKIP LOCKED + Stale-aware Zombie Reaper

Job claim (PostgreSQL path):

```sql
SELECT ... FROM jobs WHERE status = 'queued'
ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
```

Startup recovery (stale-aware, НЕ слепой reset):

```sql
UPDATE jobs
SET status = 'queued', attempt_count = attempt_count + 1
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '10 minutes'
  AND attempt_count < max_attempts
```

Job handlers ОБЯЗАНЫ быть идемпотентны (связка с R16).

### R9: Uvicorn single worker

```
uvicorn src.main:app --workers 1 --host 0.0.0.0 --proxy-headers --forwarded-allow-ips=*
```

Persistent jobs снимают главную боль от single worker.

### R10: Docker обязателен, dev/prod разделены

- `docker-compose.yml` — prod-like: api + db.
- `docker-compose.dev.yml` — dev: + MinIO + bind mounts + hot reload.
- SQLite запрещён как runtime storage. Допустим для unit tests (R11).

### R11: Двухуровневая test strategy

| Уровень | Backend | Маркер | Запуск |
|---------|---------|--------|--------|
| Unit/Logic | SQLite in-memory | (default) | Каждый push |
| Integration/Locking | PostgreSQL (GH Actions `services:`) | `@pytest.mark.integration` | Каждый PR merge |
| Full + DoD subset | PostgreSQL + DoD automation | `@pytest.mark.slow` | Nightly / pre-release |

CI details — см. [CI/CD Gate Policy](#cicd-gate-policy).

### R12: Health endpoints

- `GET /api/health` — liveness. Всегда 200 если процесс жив. Для Docker HEALTHCHECK.
- `GET /api/health/ready` — readiness. Проверяет DB (`SELECT 1`) + temp dir writable. 503 если не ready.
- S3/MinIO — отдельный degraded signal, НЕ hard fail в readiness.

Health probe использует собственный engine connect, НЕ `get_db` dependency.

### R13: Dynamic periods

```python
PERIODS_MAP = {"Daily": 1000, "Monthly": 120, "Quarterly": 40, "Annual": 20}
periods = PERIODS_MAP.get(frequency, 120)
```

### R14: Strict Join Policy

- `merge_keys` обязателен для всех merge операций.
- Перед merge — валидация уникальности ключей:
```python
if df.group_by(merge_keys).len().filter(pl.col("len") > 1).height > 0:
    raise WorkbenchError("Duplicate merge keys found!")
```

### R15: Hard Caps с конкретными defaults

```python
MAX_PREVIEW_ROWS: int = 100
MAX_CHART_POINTS: int = 500
MAX_ZIP_SIZE_MB: int = 100
MAX_EXPORT_ROWS: int = 250_000
MAX_TOKEN_USES: int = 5
MAGIC_TOKEN_TTL_HOURS: int = 48
SIGNED_URL_TTL_MINUTES: int = 10
MAX_JOB_RETRIES: int = 3
```

Все значения — в Settings, переопределяемы через env vars.

### R16: Retry только для идемпотентных operations

- tenacity / retry допустим ТОЛЬКО при наличии dedupe key или idempotency marker.
- Job retry — только для retryable status + attempt_count < max_attempts.

### R17: Token Flow — atomic, human-click gated

- Raw token криптографически стойкий, в БД — только `token_hash`.
- `max_uses = 5`, `TTL = 48h`.
- На `/downloading` запрещён auto-download. Пользователь нажимает явную кнопку.
- Resend flow: если `use_count = 0` — reuse token; если `use_count > 0` — создать новый, отменить старый.
- Rate limit resend: 1 per 2 minutes. После 3 resends — fallback с extra Turnstile challenge.

### R18: AuditEvent с typed taxonomy

Одна generic таблица. Event types — строгий Enum (см. [Event Taxonomy](#event-taxonomy)).
Retention: 90 days raw. Index: `(event_type, created_at)`.
Aggregation tables — бэклог после PMF.

### R19: Publication versioning по lineage key

```python
# Publication model:
source_product_id: str | None   # FK к CubeCatalog.product_id
version: int = 1
config_hash: str | None         # SHA256(json(chart_type, size, geo_filter, title))
content_hash: str | None        # SHA256(composite PNG bytes)
```

Version bump lineage key: `(source_product_id, config_hash)`.
Новая генерация с тем же lineage key → `max(version) + 1`.
Разные config → version 1.

S3 key: `publications/{pub_id}/v{version}/{content_hash[:8]}_lowres.png`

### R20: Graceful Shutdown

1. Stop claiming new jobs.
2. Wait up to 30s for current job to finish.
3. If still running after 30s — leave status `running` (zombie reaper подберёт по stale threshold).
4. Dispose engine, close HTTP clients.
5. Docker: `stop_grace_period: 35s`.

НЕ requeue на shutdown — race condition risk.

### R21: API Versioning Policy

- Все endpoints под `/api/v1/`.
- Breaking changes → новый prefix `/api/v2/`. Старый остаётся до deprecation.
- Additive changes (новые поля с defaults) допустимы в `/api/v1/`.
- Job payload schema versioning — отдельно от HTTP API versioning.

---

## Prerequisites Checklist

### Hard Blockers (перед Этапом 0)

```
□ VPS provisioned, Docker + Docker Compose installed
□ PostgreSQL target available (docker-compose или managed)
□ S3 bucket created: summa-vision-{env} (или MinIO strategy для dev)
□ DNS: summa.vision → Cloudflare proxy → VPS
□ DNS: api.summa.vision → VPS
□ Git repo clean (FIX-01..09 applied)
```

### Required перед Этапом D

```
□ AWS SES domain verification complete (или Resend account active)
□ SES sandbox exit approved (или Resend ready for production)
□ Cloudflare Turnstile site key получен
□ Email sending tested (dev sandbox OK)
```

### Required перед production cutover

```
□ CloudFront distribution created, OAC configured
□ DNS: cdn.summa.vision → CloudFront
□ Backup job verified (pg_dump → S3, successful restore tested)
□ Alerting tested (job failure triggers notification)
□ SSL certificates active for all domains
```

---

## Порядок этапов

```
FIX-01..09+       ← фундамент (1-2 дня)
  ↓
ЭТАП 0            ← Docker + Jobs + Audit + Backup (1 неделя)
  ↓
ЭТАП A            ← Polars Data Engine (1.5-2 недели)
  ↓
ЭТАП B            ← Visual Engine + Batch CLI (1 неделя)
  ↓
  ├─ D-0a,0b,0c   ← Email + Turnstile + Resend (2-3 дня)
  ↓
ЭТАП D            ← Public Site + Secure Funnel + Revenue (1-1.5 недели)
  ↓
ЭТАП C            ← Admin UI + Jobs Dashboard + KPI (1-1.5 недели, параллельно с revenue)
```

---

## Этап 0: Infrastructure Foundation

### 0-1: Docker + Compose + Health + MinIO + CDN config

**Scope:** Containerized environment с resource lifecycle, health checks, dev storage parity.

**Acceptance Criteria:**

- [ ] `backend/Dockerfile` создан. Base: `python:3.11-slim`. Включает: `libcairo2`, `libpango`, `fonts-noto`, `fonts-liberation`, `curl`. `ENV POLARS_MAX_THREADS=2`. CMD: uvicorn single worker с `--proxy-headers`.
- [ ] `docker-compose.yml` создан: api + db (postgres:16-alpine). API healthcheck через `/api/health`. Volumes: `pgdata`.
- [ ] `docker-compose.dev.yml` создан: bind mount `./backend:/app`, hot reload command, MinIO service (`minio/minio`), MinIO init container (creates bucket `summa-vision-dev`).
- [ ] `src/main.py` lifespan: init `data_sem(2)`, `render_sem(2)`, `io_sem(10)`. Stale-aware zombie reaper (R8) runs once on startup. Graceful shutdown (R20).
- [ ] `GET /api/health` возвращает 200 всегда. `GET /api/health/ready` проверяет DB + temp dir. Health probe НЕ использует `get_db` dependency.
- [ ] `src/core/config.py` (или `settings.py`): `CDN_BASE_URL`, `S3_BUCKET`, `S3_ENDPOINT_URL` (для MinIO в dev), `DATABASE_URL` (PostgreSQL only, no SQLite fallback in runtime).
- [ ] `docker compose up` → API responds at `localhost:8000/api/health`. `docker compose -f docker-compose.dev.yml up` → API + MinIO + hot reload.
- [ ] CairoSVG renders text without tofu (verified manually with test SVG).
- [ ] `.env.example` обновлён со всеми новыми env vars.
- [ ] `database.py`: `pool_size=8, max_overflow=8, pool_pre_ping=True`. No SQLite fallback.

**Files:** `backend/Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, `backend/src/main.py`, `backend/src/core/config.py`, `backend/src/core/database.py`, `backend/src/api/routers/health.py`

---

### 0-2: Job Model + Typed Payloads + Repository

**Scope:** Persistent job orchestration backbone с type-safe payloads.

**Acceptance Criteria:**

- [ ] `models/job.py`: `id` (PK), `job_type` (str, indexed), `status` (Enum: queued/running/success/failed/cancelled), `payload_json` (Text), `result_json` (Text, nullable), `error_code` (str, nullable), `error_message` (Text, nullable), `attempt_count` (int, default=0), `max_attempts` (int, default=3), `created_at`, `started_at` (nullable), `finished_at` (nullable), `created_by` (str, nullable), `dedupe_key` (str, nullable, unique when not null).
- [ ] `schemas/job_payloads.py`: Pydantic models с `schema_version: int = 1`:
  - `CatalogSyncPayload(schema_version)`
  - `CubeFetchPayload(schema_version, product_id: str)`
  - `TransformPayload(schema_version, source_keys: list[str], operations: list[dict])`
  - `GraphicsGeneratePayload(schema_version, data_key: str, chart_type: str, title: str, size: tuple[int,int], category: str)`
- [ ] `PAYLOAD_REGISTRY: dict[str, type[BaseModel]]` — dispatch по `job_type`.
- [ ] `parse_payload(job) -> BaseModel` — валидирует и возвращает typed payload. Unknown job_type → `UnknownJobTypeError`. Incompatible schema_version → `IncompatiblePayloadError`, job marked `failed_non_retryable`.
- [ ] `repositories/job_repository.py`:
  - `enqueue(job_type, payload, dedupe_key=None, created_by=None) -> Job`. Если `dedupe_key` уже exists в статусе queued/running → вернуть существующий job (НЕ создавать новый).
  - `claim_next(job_type=None) -> Job | None`. PostgreSQL: `FOR UPDATE SKIP LOCKED`. SQLite: simple `SELECT ... LIMIT 1` (для unit tests, без locking guarantees).
  - `mark_running(job_id)`, `mark_success(job_id, result_json)`, `mark_failed(job_id, error_code, error_message)`.
  - `list_jobs(job_type=None, status=None, limit=50) -> list[Job]`.
  - `get_job(job_id) -> Job | None`.
- [ ] Alembic migration generated and applied.
- [ ] Tests: enqueue + claim cycle; dedupe_key prevents duplicate; claim returns None when empty; mark_success persists result; schema_version mismatch handling.
- [ ] Integration test (`@pytest.mark.integration`): SKIP LOCKED behavior with PostgreSQL.

**Files:** `backend/src/models/job.py`, `backend/src/schemas/job_payloads.py`, `backend/src/repositories/job_repository.py`
**Tests:** `backend/tests/repositories/test_job_repository.py`

---

### 0-3: Job Runner + Dedupe + Retry + Shutdown Awareness

**Scope:** Safe in-process job executor.

**Acceptance Criteria:**

- [ ] `services/jobs/runner.py`: `JobRunner` class.
  - Claims jobs via `claim_next()`.
  - Dispatches to handler registry based on `job_type`.
  - Validates payload via `parse_payload()` before execution.
  - On success: `mark_success()`.
  - On retryable failure: `mark_failed()` + re-enqueue if `attempt_count < max_attempts`.
  - On non-retryable failure: `mark_failed()`, no retry.
- [ ] Shutdown awareness: runner checks `app.state.shutting_down` flag before claiming next job. Does NOT requeue currently running job on shutdown (R20).
- [ ] Dedupe enforcement: `catalog_sync` → `catalog_sync:{yyyy-mm-dd}`, `cube_fetch` → `fetch:{product_id}:{yyyy-mm-dd}`.
- [ ] Cool-down for repeated DataContractError: if last 3 jobs for same `product_id` failed with `DATA_CONTRACT_VIOLATION` within 24h, skip this cube.
- [ ] Tests: successful job execution; retryable failure + retry; non-retryable failure; dedupe prevents duplicate execution; shutdown flag stops claiming; cool-down logic.

**Files:** `backend/src/services/jobs/runner.py`, `backend/src/services/jobs/handlers.py`
**Tests:** `backend/tests/services/jobs/test_runner.py`

---

### 0-4: AuditEvent Foundation

**Scope:** Generic operational event table с typed taxonomy.

**Acceptance Criteria:**

- [ ] `models/audit_event.py`: `id`, `event_type` (str, indexed — validated against EventType enum), `entity_type` (str), `entity_id` (str), `metadata_json` (Text, nullable), `created_at` (indexed), `actor` (str, nullable).
- [ ] `EventType` enum defined (см. [Event Taxonomy](#event-taxonomy)). AuditEvent writer validates `event_type` against enum. Arbitrary strings rejected with ValueError.
- [ ] Index: `ix_audit_type_created` on `(event_type, created_at)`.
- [ ] `services/audit.py`: `AuditWriter` with `log_event(event_type, entity_type, entity_id, metadata=None, actor=None)`.
- [ ] Job runner writes: `job.created`, `job.started`, `job.succeeded`, `job.failed` events automatically.
- [ ] Settings: `AUDIT_RETENTION_DAYS = 90`.
- [ ] Alembic migration.
- [ ] Tests: write event, read back, verify fields; reject unknown event_type; verify index exists.

**Files:** `backend/src/models/audit_event.py`, `backend/src/services/audit.py`, `backend/src/schemas/events.py`
**Tests:** `backend/tests/services/test_audit.py`

---

### 0-5: Backup + Alerting Baseline

**Scope:** Minimum viable operational safety net.

**Acceptance Criteria:**

- [ ] `scripts/ops/backup_db.sh`: `pg_dump` → gzip → upload to S3 via `aws s3 cp`. Configurable via env vars: `BACKUP_S3_BUCKET`, `BACKUP_RETENTION_DAYS`.
- [ ] Cron entry documented: `0 3 * * * /app/scripts/ops/backup_db.sh` (nightly 3am).
- [ ] Structured logging: `structlog` configured for JSON output in production, console in dev. All services already use structlog (from Phase 0 PR-00).
- [ ] Alert baseline: document how to set up CloudWatch alarm / uptime monitor for:
  - API health endpoint failure (5xx for > 5 minutes).
  - Job failure rate spike (> 5 failures in 10 minutes — detectable via AuditEvent query).
- [ ] NOT in this PR: EmailService, TurnstileValidator (moved to pre-D).

**Files:** `backend/scripts/ops/backup_db.sh`, `docs/MONITORING.md`

---

## Этап A: Data Engine

### A-1: CubeCatalog Model + Bilingual FTS

**Acceptance Criteria:**

- [ ] `models/cube_catalog.py`: `id` (PK autoincrement), `product_id` (str(30), unique, indexed — R12), `cube_id_statcan` (int, indexed), `title_en` (str(500)), `title_fr` (str(500), nullable), `subject_code` (str(20), indexed), `subject_en` (str(255)), `survey_en` (str(255), nullable), `frequency` (str(20)), `start_date` (date, nullable), `end_date` (date, nullable), `archive_status` (bool, default=False), `last_synced_at` (datetime(tz), nullable).
- [ ] PostgreSQL FTS: `pg_trgm` extension enabled. Generated weighted `search_vector`. GIN index. Trigram indexes on `title_en`, `title_fr`.
- [ ] Registered in `models/__init__.py`.
- [ ] Alembic migration applied. `alembic heads` shows one head.
- [ ] Tests: CRUD cycle; product_id uniqueness constraint; search_vector populated.

### A-2: CubeCatalogRepository

**Acceptance Criteria:**

- [ ] `upsert_batch(cubes) -> int` — bulk insert/update, chunks of 500.
- [ ] `search(query, limit=20)` — `websearch_to_tsquery` + `ts_rank` + trigram similarity on title_en/title_fr. Combined relevance score.
- [ ] `get_by_product_id(product_id) -> CubeCatalog | None`
- [ ] `get_by_subject(subject_code, limit=50) -> list[CubeCatalog]`
- [ ] `count() -> int`
- [ ] Tests: insert 10, search "rental vacancy" → correct results; search typo "renal vacncy" → trigram still finds; upsert idempotent; empty search → 422 at API level.

### A-3: CatalogSyncService

**Acceptance Criteria:**

- [ ] `CatalogSyncService(client: StatCanClient, repo: CubeCatalogRepository)`
- [ ] `async sync_full_catalog() -> SyncReport(total, new, updated, errors)`
- [ ] Uses `getAllCubesList` StatCan endpoint.
- [ ] Batch upsert (chunks of 500). Respects MaintenanceGuard + AsyncTokenBucket.
- [ ] Log progress via structlog every 1000 cubes.
- [ ] Sync создаётся как persistent job с `dedupe_key = catalog_sync:{yyyy-mm-dd}`.
- [ ] Scheduler: daily 09:15 EST, timezone `America/Toronto`.
- [ ] AuditEvent: writes `job.created`, `job.succeeded` / `job.failed`.
- [ ] Tests: mock 50 cubes → all saved; sync twice same day → dedupe; SyncReport accuracy.

### A-4: Cube Search API

**Acceptance Criteria:**

- [ ] `GET /api/v1/admin/cubes/search?q=...&limit=20` — protected by AuthMiddleware. Empty q → 422.
- [ ] `POST /api/v1/admin/cubes/sync` → creates persistent job → 202 `{"job_id": "..."}`. If dedupe_key exists (same day) → returns existing job.
- [ ] `GET /api/v1/admin/cubes/{product_id}` → full metadata.
- [ ] Tests: search returns results; empty q → 422; sync → 202; sync twice → same job_id.

### A-5: DataFetchService (Polars-first)

**Acceptance Criteria:**

- [ ] `services/statcan/data_fetch.py` — Polars-native. NO import pandas. NO call to legacy `normalize_dataset()`.
- [ ] `DataFetchService(client: StatCanClient, storage: StorageInterface, catalog_repo: CubeCatalogRepository)`
- [ ] `async fetch_cube_data(product_id: str) -> FetchResult`
- [ ] Dynamic periods (R13): reads `frequency` from CubeCatalog, applies `PERIODS_MAP`.
- [ ] Pipeline stages:
  - Stage 1 (io_sem): download CSV bytes via StatCanClient.
  - Stage 2 (data_sem, run_in_threadpool): `pl.read_csv()` → clean → cast → normalize scalar factor → validate schema.
- [ ] Schema validation: `REQUIRED_COLUMNS = {"REF_DATE", "GEO", "VALUE", "SCALAR_ID"}`. Missing → `DataContractError`, log CRITICAL, fail job.
- [ ] Data quality: if `% null > 20` in VALUE → log WARNING.
- [ ] Duplicate check: uniqueness keys validated via Polars `group_by` (R14).
- [ ] Save as Parquet ONLY (R3). Key: `statcan/processed/{product_id}/{date}.parquet`.
- [ ] No DB session during heavy parse/transform stage (R6).
- [ ] Creates persistent job with `dedupe_key = fetch:{product_id}:{yyyy-mm-dd}`.
- [ ] Tests: mock StatCan response → DataFrame correct; NaN handling; schema violation → DataContractError; Parquet saved; no pandas import in file.

### A-6: DataWorkbench (Pure Polars Transforms)

**Acceptance Criteria:**

- [ ] `services/data/workbench.py` — ALL functions pure (ARCH-PURA-001). No I/O. No pandas import.
- [ ] Functions: `aggregate_time(df, freq, method)`, `filter_geo(df, geography)`, `filter_date_range(df, start, end)`, `calc_yoy_change(df, value_col)`, `calc_mom_change(df, value_col)`, `calc_rolling_avg(df, value_col, window)`, `merge_cubes(dfs, merge_keys, how)`.
- [ ] `merge_cubes`: `merge_keys` required (default `["REF_DATE", "GEO"]`). Validates keys exist. Validates keys unique (R14). Warning if result > 10x largest input.
- [ ] Every function returns NEW DataFrame.
- [ ] Tests per function with realistic StatCan-shaped data.

### A-7: Transform API

**Acceptance Criteria:**

- [ ] `POST /api/v1/admin/cubes/{product_id}/fetch` → persistent job → 202.
- [ ] `POST /api/v1/admin/data/transform` — body: `{source_keys, operations, output_key}`. Heavy transforms under `data_sem` + `run_in_threadpool`. Output = Parquet storage key. Full JSON result body forbidden.
- [ ] `GET /api/v1/admin/data/preview/{storage_key}?limit=100` — max 100 rows (R15). Typed serializer: null → None, datetime → ISO string, numeric → Python scalar.
- [ ] Tests: transform → parquet key returned; preview → correct row count; preview > limit → capped.

---

## Этап B: Visual Engine

### B-1: SVG Generator → Real Data

**Acceptance Criteria:**

- [ ] Column mapping: `VALUE`, `REF_DATE`, `GEO` (StatCan names).
- [ ] Date parsing: "2024-01" → datetime.
- [ ] Downsample if > 500 points (R15).
- [ ] `chart_config` parameter: title, x_label, y_label, color_palette, show_legend.
- [ ] Tests: real-shaped DataFrame → SVG output starts with `<svg`; dimensions match; downsample triggers.

### B-2: Template Backgrounds

**Acceptance Criteria:**

- [ ] 6 categories: housing, inflation, employment, trade, energy, demographics. 3 variants each.
- [ ] Dark theme (#141414 base), subtle gradients, neon accents, negative space in upper-third.
- [ ] `get_background(category, size) -> bytes`.
- [ ] Stored in `backend/assets/backgrounds/`.
- [ ] Tests: each category returns valid PNG bytes; dimensions match requested size.

### B-3: End-to-End Pipeline (Versioned, Resilient)

**Acceptance Criteria:**

- [ ] `services/graphics/pipeline.py`: `GraphicPipeline.generate(data_key, chart_type, title, size, category) -> GenerationResult(publication_id, cdn_url_lowres, s3_key_highres)`.
- [ ] Rendering under `render_sem`, uploads under `io_sem`.
- [ ] Publication versioning (R19): `source_product_id` + `config_hash` → lineage key. New version = `max(version) + 1`. S3 key includes version + content_hash.
- [ ] Lowres → public S3 prefix → CDN URL (R1). Highres → private prefix.
- [ ] ZIP via temp files, strict cleanup.
- [ ] Explicit failure modes with try/finally cleanup:
  1. Chart gen fails → job fails.
  2. Background fails → job fails.
  3. Composite fails → cleanup temp → job fails.
  4. Upload lowres fails → cleanup temp → job fails (retryable).
  5. Upload highres/ZIP fails → cleanup temp + delete lowres → job fails.
  6. DB update fails → S3 orphan acceptable (cleanup cron later).
- [ ] AuditEvent: `publication.generated`, `publication.published`.
- [ ] Tests: mock pipeline → correct call sequence; failure at each stage → correct cleanup; version increments.

### B-4: Admin Graphics API + Batch CLI

**Acceptance Criteria:**

- [ ] `POST /api/v1/admin/graphics/generate` → persistent job → 202.
- [ ] `scripts/ops/generate_batch.py`: direct service imports allowed (ops script category). Accepts `--cubes`, `--chart-type`, `--size`. Prints per-item result. Bounded concurrency.
- [ ] Smoke test: `test_batch_script_imports()` verifies imports don't break.
- [ ] Tests: generate endpoint → 202 + job_id; batch script imports successfully.

**ЧЕКПОИНТ B:** 10 графиков сгенерированы через Swagger UI или batch CLI. 10 Publication records в БД, status=PUBLISHED, version=1.

---

## Этап D: Public Site + Revenue

### D-0a: EmailService + Provider (before D-2)

**Acceptance Criteria:**

- [ ] `services/email/interface.py`: `EmailServiceInterface` with `async send_email(to, subject, html_body)`.
- [ ] `services/email/ses_provider.py` (or `resend_provider.py`): concrete implementation. Provider chosen via Settings.
- [ ] Tests: mock provider → verify send called with correct args; provider selection from settings.

### D-0b: TurnstileValidator (before D-2)

**Acceptance Criteria:**

- [ ] `services/security/turnstile.py`: `TurnstileValidator.validate(token: str, ip: str) -> bool`. HTTP POST to `https://challenges.cloudflare.com/turnstile/v0/siteverify`.
- [ ] Settings: `TURNSTILE_SECRET_KEY`.
- [ ] Tests: mock Cloudflare response → success/failure paths.

### D-0c: DownloadToken Model + Resend Flow (before D-2)

**Acceptance Criteria:**

- [ ] `models/download_token.py`: `id`, `token_hash` (str, unique indexed), `lead_id` (FK), `expires_at`, `use_count` (int, default=0), `max_uses` (int, default=5), `created_at`, `revoked` (bool, default=False).
- [ ] Token generation: `secrets.token_urlsafe(32)`. Store SHA256 hash only.
- [ ] Atomic usage: `UPDATE ... SET use_count = use_count + 1 WHERE token_hash = ? AND use_count < max_uses AND expires_at > NOW() AND revoked = false RETURNING *`.
- [ ] Resend logic: if `use_count = 0` → reuse token. If `use_count > 0` → create new token, revoke old.
- [ ] Alembic migration.
- [ ] Tests: create token → exchange → use_count increments; expired token rejected; exhausted token rejected; revoked token rejected; resend creates new when partially used.

### D-1: Next.js Gallery → Real API

**Acceptance Criteria:**

- [ ] `InfographicFeed` consumes `cdn_url` from gallery API. ISR `revalidate: 3600`.
- [ ] `images.remotePatterns` configured for CDN domain. Normal Next Image optimization (NOT `unoptimized` by default).
- [ ] SEO: `og:image` meta tags per graphic.
- [ ] Secure revalidation endpoint: `POST /api/revalidate` with secret verification.
- [ ] Tests: component renders image cards; revalidation endpoint rejects invalid secret.

### D-2: Lead Capture + Secure Download

**Acceptance Criteria:**

- [ ] `DownloadModal`: Turnstile widget. Email input + Zod validation.
- [ ] Backend flow: validate Turnstile → save lead → generate token → send email with Magic Link → return 200 "Check your email".
- [ ] `/downloading` page: reads token from URL → clears URL → shows "Verify and Download" button (NO auto-download). On click → `window.location.assign(download_url)`.
- [ ] Backend download endpoint: validate token atomically → generate presigned URL (10 min) → 307 redirect.
- [ ] Rate limit: 3/min per IP on lead capture. 1 resend / 2 min.
- [ ] AuditEvents: `lead.captured`, `lead.email_sent`, `token.activated`.
- [ ] Tests: full flow with mocked email; expired token → 403; exhausted token → 403; resend works; Turnstile failure → 403.

### D-3: B2B Scoring + Notifications

**Acceptance Criteria:**

- [ ] `LeadScoringService`: categories b2b, education, isp, b2c. Domain lists per Phase 5 spec.
- [ ] `SlackNotifierService`: webhook, dedupe_key required. b2b → Slack, education → Slack+tag, isp → DB only, b2c → handled by form validation.
- [ ] Background task in lead capture. Idempotent (R16).
- [ ] `POST /api/v1/admin/leads/resync` for ESP sync.
- [ ] Tests: gmail→b2c; rogers→isp; utoronto→education; tdbank→b2b; Slack called for b2b.

### D-4: Partner Page

**Acceptance Criteria:**

- [ ] `/partner-with-us` static page. 3 pricing tiers from `constants/pricing.ts`.
- [ ] Inquiry form: Zod validation, reject free email domains on client side.
- [ ] `POST /api/v1/public/sponsorship/inquire`. Rate limit: 1/5min per IP. Slack notification with dedupe.
- [ ] Tests: renders 3 tiers; gmail rejected; valid corporate email → 200.

### D-5: First Distribution (Checklist, not code)

```
□ AWS SES out of sandbox / Resend production ready
□ 10 graphics generated for top Canadian macro themes
□ summa.vision deployed (Vercel for Next.js, VPS Docker for API)
□ Post to Reddit: r/canada, r/canadahousing, r/PersonalFinanceCanada
□ Post to X: #cdnpoli #cdnecon #housingcrisis
□ Each post: graphic + headline + link to summa.vision
□ Offer: "Download the clean dataset in CSV for your own analysis"
□ Verify: resend flow works, bounce handling works, backup runs, alerts trigger
□ Track: lead_captured, email_sent, token_activated, verified_downloads
□ Goal: 50 verified downloads in first week
□ If < 10: reassess content, channels, headlines
```

---

## Этап C: Admin UI

### C-1: Cube Search Screen
- Search bar с debounce. Results: title, subject, frequency. Tap → detail + "Fetch Data".

### C-2: Data Preview Screen
- Parquet preview (first 100 rows). Filter controls. Schema inspection.

### C-3: Chart Config + Generation Screen
- Dataset selector. Chart type, size preset, title. Generate button → job → polling → result.

### C-4: Jobs Dashboard
- Jobs list: status, type, started_at, finished_at, operator, error summary.
- Retry button for retryable failed jobs. Dedupe info visible. Stale/zombie visibility.

### C-5: KPI Screen
- Data from AuditEvent + domain tables.
- Metrics: publications, leads, emails, token activations, verified downloads, failed jobs by type.

---

## Бэклог

| Фича | Когда |
|------|-------|
| CMHC Playwright scraping | Когда исчерпаем StatCan темы |
| LLM headline generation | Когда >20 графиков/день |
| AI background generation | Когда будет бюджет на API |
| JWT for external B2B clients | Когда появятся внешние API consumers |
| Full BI/warehouse layer | После PMF |
| AuditEvent daily aggregation | Когда raw events > 10k/day |
| Redis job queue | Когда >1 worker process needed |
| Polars migration for legacy StatCan code | Когда legacy ETL требует значительных изменений |

---

## CI/CD Gate Policy

```yaml
# Push gate (every push, ~30s):
- pytest -m "not integration and not slow" --tb=short -q
- mypy src/ --no-error-summary
- black --check src/ tests/

# PR gate (every PR to main, ~3min):
- pytest -m "not slow" --cov=src --cov-fail-under=85
  # Includes integration tests with PostgreSQL (GH Actions services: block)
- alembic upgrade head && alembic downgrade -1 && alembic upgrade head

# Nightly (scheduled, ~10min):
- pytest --cov=src --cov-report=html
- python -m tests.test_dod  # automated DoD checks
```

Test markers:
- (unmarked) = unit test, SQLite, fast
- `@pytest.mark.integration` = needs PostgreSQL
- `@pytest.mark.slow` = expensive/long-running

---

## Secret Management Policy

| Environment | Storage | Access |
|-------------|---------|--------|
| Dev | `.env` file (git-ignored) | Developer only |
| Prod | Environment variables injected by deploy process | No secrets in repo, no `.env` on server |

Startup validation: Settings class validates required secrets by stage.
Missing required secret → app refuses to start with clear error message.

Secret rotation: documented in `docs/OPERATIONS.md` (created in 0-5).

---

## Deploy Compatibility Rules

1. Job payload models ALWAYS backward-compatible: new fields have defaults.
2. If breaking payload change unavoidable: drain job queue before deploy (wait for all queued/running → success/failed).
3. Alembic migrations run BEFORE new code starts: `alembic upgrade head` in container entrypoint.
4. Never delete/rename a DB column that running jobs reference until old jobs are drained.
5. API additive changes OK in `/api/v1/`. Breaking changes → `/api/v2/`.

---

## S3 Key Naming Convention

```python
# Raw StatCan downloads
RAW_KEY      = "statcan/raw/{product_id}/{yyyy-mm-dd}.csv"

# Processed Parquet (internal, never public)
PROCESSED_KEY = "statcan/processed/{product_id}/{yyyy-mm-dd}.parquet"

# Published graphics (lowres = CDN-accessible, highres = private)
PUB_LOWRES   = "publications/{pub_id}/v{version}/{content_hash[:8]}_lowres.png"
PUB_HIGHRES  = "publications/{pub_id}/v{version}/{content_hash[:8]}_highres.png"
PUB_ZIP      = "publications/{pub_id}/v{version}/archive.zip"

# Backups
BACKUP_KEY   = "backups/{yyyy-mm-dd}/summa_{timestamp}.sql.gz"
```

---

## Event Taxonomy

```python
class EventType(str, Enum):
    # Jobs
    JOB_CREATED = "job.created"
    JOB_STARTED = "job.started"
    JOB_SUCCEEDED = "job.succeeded"
    JOB_FAILED = "job.failed"

    # Leads
    LEAD_CAPTURED = "lead.captured"
    LEAD_EMAIL_SENT = "lead.email_sent"
    LEAD_EMAIL_BOUNCED = "lead.email_bounced"

    # Tokens
    TOKEN_CREATED = "token.created"
    TOKEN_ACTIVATED = "token.activated"
    TOKEN_EXHAUSTED = "token.exhausted"
    TOKEN_EXPIRED = "token.expired"
    TOKEN_REVOKED = "token.revoked"

    # Publications
    PUBLICATION_GENERATED = "publication.generated"
    PUBLICATION_PUBLISHED = "publication.published"

    # System
    CATALOG_SYNCED = "catalog.synced"
    DATA_CONTRACT_VIOLATION = "data.contract_violation"
```

Arbitrary strings outside this enum are rejected by AuditWriter.

---

## Definition of Done

### Automated (verified in CI via `tests/test_dod.py`)

- [ ] No `import pandas` in Polars-path files (`data_fetch.py`, `workbench.py`, `pipeline.py`)
- [ ] `POLARS_MAX_THREADS` set in Dockerfile
- [ ] All hard caps defined in Settings with non-zero defaults
- [ ] Health endpoints return expected status codes
- [ ] Parquet-only in `statcan/processed/` path (no `.csv` writes)
- [ ] EventType enum covers all event_type values used in codebase
- [ ] No `time.sleep` in async code paths
- [ ] No `allow_origins=["*"]` in CORS config
- [ ] Alembic has exactly one head

### Manual QA (checklist before release)

- [ ] `docker compose up` → healthy in < 60s
- [ ] CairoSVG renders text without tofu squares
- [ ] CDN URL loads lowres image in browser
- [ ] Token exchange flow works end-to-end (email → click → download)
- [ ] Auto-download does NOT trigger on `/downloading` page load
- [ ] Download works via browser navigation (not fetch)
- [ ] Resend flow creates new token when old partially used
- [ ] Backup script runs and produces valid SQL dump
- [ ] Jobs dashboard shows correct statuses after server restart
- [ ] Zombie reaper only requeues stale (>10min) jobs

### Operational Readiness

- [ ] All required secrets validated at startup
- [ ] Structured logs output to stdout in JSON
- [ ] Job failure alerts configured and tested
- [ ] PostgreSQL backup verified (restore to test instance)
- [ ] DNS, SSL, CDN configured for production domains
- [ ] SES/Resend out of sandbox

---

## Итоговая сводка

| Этап | PR | Время | Результат |
|------|-----|-------|-----------|
| Fixes | ~15 | 2 дня | Чистый фундамент |
| 0: Infra | 5 | 1 неделя | Docker, jobs, audit, backup |
| A: Data Engine | 7 | 1.5–2 недели | Polars pipeline + search + contracts |
| B: Visual Engine | 4 | 1 неделя | Versioned publish + batch CLI |
| D-0: Pre-launch | 3 | 2–3 дня | Email, Turnstile, tokens |
| D: Public + Revenue | 5 | 1–1.5 недели | Secure funnel + first distribution |
| C: Admin UI | 5 | 1–1.5 недели | Jobs dashboard + KPI |
| **ИТОГО** | **~44** | **~7–8 недель** | **Production MVP с revenue** |

Первые деньги: неделя 6 (после D-5).
Admin UI: неделя 7–8 (не блокирует revenue).
