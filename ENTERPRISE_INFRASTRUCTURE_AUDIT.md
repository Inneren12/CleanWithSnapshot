# ENTERPRISE INFRASTRUCTURE & CI/CD AUDIT REPORT

**Date:** 2025-05-23
**Auditor:** Jules (Principal SRE)
**Scope:** Infrastructure, Container Security, CI/CD, Operations

---

## 1. Executive Summary

**Infrastructure & Security Scorecard**

| Domain | Status | Key Issues |
| :--- | :---: | :--- |
| **Container Security** | 🔴 **CRITICAL** | Privileged Docker socket mount (Root Escalation Risk), Floating tags (`latest`), Running as root. |
| **Deployment Strategy** | 🟠 **HIGH RISK** | "Pull & Restart" causes downtime, destructive git rollback (`reset --hard`), in-place production builds. |
| **CI/CD Maturity** | 🟡 **MODERATE** | Redundant builds (wasteful), hardcoded secrets in workflows, unsafe smoke tests. |
| **Resilience & Ops** | 🟡 **MODERATE** | Backups exist but are local-only (single point of failure), no retention policy, restore fails on active connections. |

---

## 2. Critical Findings (P1 - Immediate Action Required)

### 🚨 [P1] Privileged Docker Socket Exposure (Root Compromise Risk)
- **File**: `docker-compose.observability.yml`
- **Snippet**:
  ```yaml
  promtail:
    # ...
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
  ```
- **Finding**: The `promtail` service in `docker-compose.observability.yml` mounts `/var/run/docker.sock` read-only.
- **Risk**: Even read-only access allows an attacker to enumerate containers, inspect environment variables (often containing secrets), and potentially escalate privileges to root on the host.
- **Remediation**: Remove the socket mount. Use the Docker logging driver or deploy a restricted socket proxy sidecar.

### 🚨 [P1] Mutable "Pull & Restart" Deployment (Guaranteed Downtime)
- **File**: `deploy.sh`
- **Snippet**:
  ```bash
  cd /opt/cleaning/backend
  git pull

  cd /opt/cleaning
  docker compose up -d --build
  ```
- **Finding**: `deploy.sh` performs a `git pull` followed by `docker compose up -d --build` on the production server.
- **Risk**: This strategy guarantees downtime during the build/restart phase. If the build fails or `git pull` results in a merge conflict, the production environment is left in an inconsistent or broken state.
- **Remediation**: Shift to immutable infrastructure. Build Docker images in CI, tag with the commit SHA, push to a registry, and deploy pre-built artifacts.

### 🚨 [P1] Hardcoded Secrets in CI/Env Vars
- **File**: `.github/workflows/ci.yml`
- **Snippet**:
  ```yaml
    env:
      POSTGRES_PASSWORD: postgres
  ```
- **Finding**: Secrets like `POSTGRES_PASSWORD` are hardcoded in `.github/workflows/ci.yml` and passed as plain environment variables in `docker-compose.yml`.
- **Risk**: Secrets are visible in process lists, `docker inspect`, and potentially logged. Copy-pasting CI configs to production leaks credentials.
- **Remediation**: Use Docker Secrets (swarm/compose) or a dedicated secret manager. Inject secrets from GitHub Actions Secrets only.

---

## 3. High Priority Improvements (P2 - Fix within Sprint/Quarter)

### 🔒 Container Hardening
- **Floating Tags**: Replace `image: postgres:16` with immutable digests (e.g., `postgres:16.2@sha256:...`) to prevent supply chain attacks.
  - **File**: `docker-compose.yml`
  - **Snippet**:
    ```yaml
    db:
      image: postgres:16
    ```
- **Root Users**: Ensure all services (especially Node.js) run as a non-root user (`USER app`) to limit blast radius.
  - **File**: `web/Dockerfile`
  - **Snippet**:
    ```dockerfile
    # (No USER instruction or runs as root)
    CMD ["node", ...]
    ```
- **Capabilities**: Drop all capabilities (`cap_drop: [ALL]`) and add only what is strictly necessary.
  - **File**: `docker-compose.yml`
  - **Snippet**:
    ```yaml
    # (No cap_drop defined)
    ```
- **Read-Only FS**: Mount root filesystems as read-only (`read_only: true`) to prevent malware persistence.
  - **File**: `docker-compose.yml`
  - **Snippet**:
    ```yaml
    # (No read_only: true defined)
    ```

### 🚀 CI/CD Efficiency & Safety
- **Redundant Builds**: Stop rebuilding images in `smoke-compose` job; reuse artifacts built in `container-scan`.
  - **File**: `.github/workflows/ci.yml`
  - **Snippet**:
    ```yaml
      - name: Start Docker Compose stack (smoke)
        run: |
          docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d --wait db redis api web
    ```
- **Unsafe Smoke Tests**: Update `ops/smoke.sh` to use dynamic URLs instead of hardcoded production domains.
  - **File**: `ops/smoke.sh`
  - **Snippet**:
    ```bash
    if curl -fsS https://api.panidobro.com/healthz >/dev/null 2>&1; then
    ```
- **Network Isolation**: Segment `docker-compose.yml` into `frontend` and `backend` networks to isolate the database.
  - **File**: `docker-compose.yml`
  - **Snippet**:
    ```yaml
    # (No networks defined)
    ```

### 🛠️ Operational Resilience
- **Offsite Backups**: Update `ops/backup_now.sh` to sync backups to S3/remote storage immediately.
  - **File**: `ops/backup_now.sh`
  - **Snippet**:
    ```bash
    # (No sync command)
    echo "[backup] complete"
    ```
- **Retention Policy**: Implement a rotation policy to delete old backups and prevent disk exhaustion.
  - **File**: `ops/backup_now.sh`
  - **Snippet**:
    ```bash
    # (No deletion logic)
    ```
- **Safer Restore**: Modify `restore_to_staging.sh` to terminate active connections before dropping the database.
  - **File**: `ops/restore_to_staging.sh`
  - **Snippet**:
    ```bash
    "${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";"'
    ```

---

## 4. Strategic Roadmap

**Sprint 1: Critical Security & Stability**
1.  Remove Docker socket mount from Promtail.
2.  Refactor `deploy.sh` to use pre-built images (tagging strategy).
3.  Implement offsite backup sync (`wal_archive_sync.sh` enhancements).

**Sprint 2: Hardening & Compliance**
1.  Pin all Docker images to SHA256 digests.
2.  Implement `USER` directives and `cap_drop` in Compose/Dockerfiles.
3.  Migrate secrets to Docker Secrets management.

**Quarter 1: Maturity & Scalability**
1.  Full Blue/Green deployment with Caddy (zero-downtime).
2.  Automated restore testing in CI (verify backups are valid).
3.  Network segmentation and strict firewall rules.
