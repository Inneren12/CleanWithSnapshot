# CI Supply Chain Hardening

## Overview
This document summarizes supply chain hardening changes in CI to eliminate unsafe
remote script execution and ensure tooling is pinned and verifiable.

## What was removed
- `curl | sh` installer for Trivy in `.github/workflows/ci.yml`.
- `curl | sh` installer for Grype in `.github/workflows/ci.yml`.
- `curl | sh` installer for Syft in `.github/workflows/ci.yml`.

## What replaced it
- Trivy scans now use the official GitHub Action pinned by SHA:
  - `aquasecurity/trivy-action@1f0aa582c8c8f5f7639610d6d38baddfea4fdcee`
  - The action runs image scans and produces JSON/SARIF outputs directly.
- Grype scans now use the official GitHub Action pinned by SHA:
  - `anchore/scan-action@62b74fb7bb810d2c45b1865f47a77655621862a5`
  - The Grype version is explicitly pinned to `v0.105.0`.
- Syft SBOM generation now uses the official GitHub Action pinned by SHA:
  - `anchore/sbom-action@62ad5284b8ced813296287a0b63906cb364b73ee`
  - The Syft version is explicitly pinned to `v1.40.1`.

## Why this is safer
- **No remote shell execution:** Eliminates piping remote scripts to `sh`, which
  removes a common vector for supply chain compromise.
- **Immutable pinning:** Actions are pinned by commit SHA, preventing upstream
  changes from silently altering CI behavior.
- **Version control for tools:** Explicit tool versions ensure deterministic,
  auditable scans across CI runs.
