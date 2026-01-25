# Grype Image Scanning Policy

## Purpose

This policy defines how CI enforces container vulnerability scanning with Grype. The goal is to
fail builds on critical findings while retaining artifact reports for review.

## Scope

- Images built by CI for the API and web services.
- Grype runs as part of the CI workflow to scan those images.

## Enforcement

- Grype is executed with `--fail-on critical`.
- Any critical findings cause the Grype job to fail.
- JSON reports are uploaded as CI artifacts for auditing.

## SBOM (Optional)

- When SBOM generation is enabled in the CI workflow, Syft produces SPDX JSON artifacts for the
  API and web images.
- SBOM artifacts are uploaded alongside the Grype reports.

## Exceptions

- Exceptions require security review and documented approval.
