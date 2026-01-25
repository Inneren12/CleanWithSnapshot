# CleanWithSnapshot / PaniDobro

Multi-tenant SaaS application for cleaning service operations management.

**Tech Stack:** FastAPI (Python) + Next.js + PostgreSQL + Redis

---

## Quick Start

**Toolchain versions:**

This repo pins the local runtime versions in `.python-version` and `.nvmrc` to match CI.
Use your preferred version manager to load them (e.g., `pyenv install --skip-existing $(cat .python-version)` and `nvm install`).

**Development:**

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Web
cd web
npm install
npm run dev
```

**Production:**

```bash
cd /opt/cleaning
./ops/deploy.sh
```

---

## Documentation

**Start here:** 📚 [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture and getting started

### System Documentation

| Document | Purpose |
|----------|---------|
| [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) | Project architecture, tech stack, how to run locally |
| [MODULES.md](./MODULES.md) | Feature modules map - where to find/change specific features |
| [FILE_OVERVIEW.md](./FILE_OVERVIEW.md) | Repository structure - important files and what they do |
| [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) | Coding conventions and contribution guidelines |
| [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) | Database migration management with Alembic |
| [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) | API reference - endpoints, auth, usage examples |
| [OPERATIONS.md](./OPERATIONS.md) | Deployment, monitoring, troubleshooting |
| [docs/SECURITY_VULN_POLICY.md](./docs/SECURITY_VULN_POLICY.md) | Vulnerability gating policy and waiver process |

### Additional Documentation

- [RUNBOOK.md](./RUNBOOK.md) - Operations runbook
- [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md) - Admin features guide
- [docs/ENV_AUDIT_REPORT.md](./docs/ENV_AUDIT_REPORT.md) - Environment variables
- [docs/DEPLOY_RUNBOOK.md](./docs/DEPLOY_RUNBOOK.md) - Deployment details
- [docs/SMOKE.md](./docs/SMOKE.md) - Smoke testing

---

## Key Questions Answered

**"Where is schedule week view implemented?"**
→ See [MODULES.md - Schedule](./MODULES.md#2-schedule)

**"Where are invoice bulk actions implemented?"**
→ See [MODULES.md - Invoices](./MODULES.md#3-invoices)

**"How do I add a new admin route and guard it?"**
→ See [CONTENT_GUIDE.md - Add a New API Route](./CONTENT_GUIDE.md#add-a-new-api-route)

**"How do I create/merge Alembic migrations?"**
→ See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md)

---

## Production URLs

- **API:** https://api.panidobro.com
- **Web:** https://panidobro.com
- **Health:** https://api.panidobro.com/healthz

---

## License

Proprietary
