# CI Gates and Branch Protection

This document describes the CI checks and branch protection configuration required to prevent merging failing code into the main branch.

## Overview

The CleanWithSnapshot repository uses GitHub Actions for continuous integration. All pull requests must pass the following checks before they can be merged to the `main` branch:

1. **API Lint** - Code quality checks using ruff
2. **API Unit Tests** - Unit test suite (excluding smoke and postgres tests)
3. **API Prod Config Validation** - Production configuration validation
4. **Web Typecheck** - TypeScript type checking
5. **Web Build** - Next.js build verification
6. **Infrastructure Validation** - docker-compose.yml and bash script validation

## CI Workflow Jobs

The CI workflow (`.github/workflows/ci.yml`) runs automatically on:
- Pull requests to `main`
- Pushes to `main`

### 1. API - Build & Test

**Job Name**: `api`

Checks performed:
- Python 3.11 environment setup
- Install dependencies from `requirements.txt`
- **Run linter (ruff)**: Checks code quality against rules E, F, W, C90, I, N, UP (ignoring E501 line length)
- **Run unit tests**: Executes pytest with SQLite in-memory database, excluding smoke and postgres-specific tests

**Required for merge**: ✅ YES

### 2. Web - Build

**Job Name**: `web`

Checks performed:
- Node.js 22 environment setup
- Install dependencies via `npm ci`
- **Run typecheck**: Executes TypeScript compiler in check mode (`tsc --noEmit`)
- **Build application**: Runs Next.js production build

**Required for merge**: ✅ YES

### 3. API - Prod Config Validation

**Job Name**: `api-prod-config`

Checks performed:
- Validates that production configuration can be loaded
- Ensures prod mode settings enforcement works correctly
- Tests with CI-safe dummy secrets

**Required for merge**: ✅ YES

### 4. Infrastructure - Validation

**Job Name**: `infra`

Checks performed:
- Validates `docker-compose.yml` syntax
- Checks bash scripts for syntax errors

**Required for merge**: ✅ YES

## Configuring Branch Protection

To enforce these CI gates, configure GitHub branch protection rules for the `main` branch.

### Step 1: Navigate to Branch Protection Settings

1. Go to your GitHub repository
2. Click **Settings** → **Branches**
3. Under "Branch protection rules", click **Add rule** or edit the existing rule for `main`

### Step 2: Configure Protection Rules

Set the following options:

#### Basic Protection

- ✅ **Require a pull request before merging**
  - ✅ **Require approvals**: 1 (recommended)
  - ✅ **Dismiss stale pull request approvals when new commits are pushed** (optional)

- ✅ **Require status checks to pass before merging**
  - ✅ **Require branches to be up to date before merging** (recommended)

#### Required Status Checks

Add these required status checks (exact names from CI workflow):

1. `API - Build & Test`
2. `Web - Build`
3. `API - Prod Config Validation`
4. `Infrastructure - Validation`

**Note**: The status check names must match exactly as they appear in the CI workflow `name` fields.

#### Additional Recommendations

- ✅ **Require conversation resolution before merging** (optional but recommended)
- ✅ **Do not allow bypassing the above settings** (enforce for administrators)
- ✅ **Allow force pushes**: ❌ Disabled (recommended)
- ✅ **Allow deletions**: ❌ Disabled (recommended)

### Step 3: Verify Configuration

1. Create a test branch with intentional failures
2. Open a pull request to `main`
3. Verify that:
   - CI runs automatically
   - Failing checks block the merge button
   - All checks must be green before merge is allowed

## CI Check Details

### API Linting (ruff)

**Purpose**: Enforce code quality standards and catch common errors.

**Rules enabled**:
- `E`: pycodestyle errors
- `F`: Pyflakes errors (unused imports, undefined names)
- `W`: pycodestyle warnings
- `C90`: McCabe complexity
- `I`: isort (import ordering)
- `N`: pep8-naming conventions
- `UP`: pyupgrade (modern Python syntax)

**Ignored rules**:
- `E501`: Line too long (ignored to allow flexibility)

**Command**:
```bash
cd backend
ruff check app/ tests/ --select E,F,W,C90,I,N,UP --ignore E501
```

**Common failures**:
- Unused imports
- Undefined variables
- Import ordering issues
- Naming convention violations

**How to fix locally**:
```bash
cd backend
pip install ruff
ruff check app/ tests/ --select E,F,W,C90,I,N,UP --ignore E501 --fix
```

### API Unit Tests (pytest)

**Purpose**: Ensure core functionality works correctly.

**Test scope**:
- Excludes `smoke` marker (integration tests requiring full stack)
- Excludes `postgres` marker (tests requiring PostgreSQL)
- Uses SQLite in-memory database for fast execution

**Command**:
```bash
cd backend
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --tb=short
```

**Common failures**:
- Logic errors in application code
- Broken test assumptions
- Dependency issues

**How to fix locally**:
```bash
cd backend
pip install -r requirements.txt
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke
```

### Web Typecheck (TypeScript)

**Purpose**: Catch type errors before runtime.

**Command**:
```bash
cd web
npx tsc --noEmit
```

**Common failures**:
- Type mismatches
- Missing type definitions
- Incorrect prop types
- Null/undefined handling issues

**How to fix locally**:
```bash
cd web
npm install
npx tsc --noEmit
# Review errors and fix type issues
```

### Web Build (Next.js)

**Purpose**: Ensure production build succeeds.

**Command**:
```bash
cd web
npm run build
```

**Common failures**:
- TypeScript errors (if typecheck passes, this is rare)
- Build configuration issues
- Missing environment variables
- Import errors

**How to fix locally**:
```bash
cd web
npm install
NEXT_PUBLIC_API_BASE_URL="http://localhost:8000" npm run build
```

## Pre-Commit Checks (Recommended)

To catch issues before pushing, set up pre-commit hooks:

### Backend Pre-Commit Hook

Create `.git/hooks/pre-commit` (or use a tool like `pre-commit`):

```bash
#!/bin/bash
set -e

echo "Running backend linter..."
cd backend
ruff check app/ tests/ --select E,F,W,C90,I,N,UP --ignore E501

echo "Running backend tests..."
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --tb=short

cd ..
echo "✓ Backend checks passed"
```

### Web Pre-Commit Hook

```bash
#!/bin/bash
set -e

echo "Running web typecheck..."
cd web
npx tsc --noEmit

cd ..
echo "✓ Web checks passed"
```

### Using pre-commit Framework (Recommended)

Install `pre-commit`:
```bash
pip install pre-commit
```

Create `.pre-commit-config.yaml` in repository root:
```yaml
repos:
  - repo: local
    hooks:
      - id: backend-lint
        name: Backend Lint (ruff)
        entry: bash -c 'cd backend && ruff check app/ tests/ --select E,F,W,C90,I,N,UP --ignore E501'
        language: system
        pass_filenames: false

      - id: backend-test
        name: Backend Unit Tests
        entry: bash -c 'cd backend && pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --tb=short'
        language: system
        pass_filenames: false

      - id: web-typecheck
        name: Web Typecheck
        entry: bash -c 'cd web && npx tsc --noEmit'
        language: system
        pass_filenames: false
```

Install hooks:
```bash
pre-commit install
```

## Troubleshooting CI Failures

### CI is not running

**Symptoms**:
- Pull request shows no checks
- CI workflow not triggered

**Solutions**:
- Ensure `.github/workflows/ci.yml` exists on the target branch
- Check workflow triggers include your branch pattern
- Verify GitHub Actions is enabled for the repository (Settings → Actions)

### Checks are failing but pass locally

**Possible causes**:
1. **Environment differences**:
   - CI uses Python 3.11, Node 22 - ensure local environment matches
   - CI uses fresh environment - try `docker compose down -v` locally

2. **Dependency version mismatch**:
   - CI uses pinned versions from lock files
   - Run `pip install -r requirements.txt` or `npm ci` (not `npm install`)

3. **Environment variables**:
   - CI uses specific env vars (check workflow file)
   - Local `.env` may differ from CI

**Debug steps**:
```bash
# Replicate CI environment locally with Docker
docker run -it --rm -v $(pwd):/workspace -w /workspace/backend python:3.11 bash
pip install -r requirements.txt
pip install ruff
ruff check app/ tests/ --select E,F,W,C90,I,N,UP --ignore E501
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --tb=short
```

### Ruff linting fails

**Common issues**:

1. **Unused imports**:
   ```python
   # Bad
   from module import UnusedClass

   # Fix: Remove unused import
   ```

2. **Undefined variables**:
   ```python
   # Bad
   result = undefined_variable

   # Fix: Define or import the variable
   ```

3. **Import order**:
   ```python
   # Bad
   from app.module import something
   import os

   # Fix (standard library first, then third-party, then local)
   import os
   from app.module import something
   ```

**Auto-fix many issues**:
```bash
cd backend
ruff check app/ tests/ --select E,F,W,C90,I,N,UP --ignore E501 --fix
```

### TypeScript typecheck fails

**Common issues**:

1. **Type mismatches**:
   ```typescript
   // Bad
   const value: string = 123;

   // Fix
   const value: string = "123";
   // OR
   const value: number = 123;
   ```

2. **Missing type definitions**:
   ```typescript
   // Bad (if @types/node is missing)
   const env = process.env.NODE_ENV;

   // Fix: Install type definitions
   // npm install --save-dev @types/node
   ```

3. **Strict null checks**:
   ```typescript
   // Bad
   const user = getUser(); // might be null
   console.log(user.name); // Error: Object is possibly null

   // Fix
   const user = getUser();
   if (user) {
     console.log(user.name);
   }
   ```

## Environment Separation Notes

### Development (`APP_ENV=dev`)
- Relaxed validation
- Faster iteration
- Local smoke tests can skip certain checks

### Staging
- Should mirror production CI gates
- Full smoke tests required
- Acts as final verification before production

### Production (`APP_ENV=prod`)
- All CI gates enforced
- No bypassing allowed
- Strict configuration validation
- Zero tolerance for failing checks

## Updating CI Gates

To add new checks to CI:

1. **Modify `.github/workflows/ci.yml`**:
   ```yaml
   - name: New Check Name
     run: |
       # Your check command
   ```

2. **Test the change on a branch**:
   - Create a test PR
   - Verify the check runs correctly

3. **Update branch protection**:
   - Add the new check name to required status checks
   - Test that it blocks merging when failing

4. **Update this documentation**:
   - Add the new check to the list above
   - Document how to run it locally
   - Add troubleshooting guidance

## References

- **CI Workflow**: `.github/workflows/ci.yml`
- **Release Checklist**: [RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md)
- **Deployment Runbook**: [DEPLOY_RUNBOOK.md](./DEPLOY_RUNBOOK.md)
- **GitHub Docs**: [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- **GitHub Docs**: [About status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/about-status-checks)

---

**Last Updated**: 2026-01-06
**Version**: 1.0
