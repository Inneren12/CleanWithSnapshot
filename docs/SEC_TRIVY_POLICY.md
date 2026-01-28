# Trivy Container Scanning Policy

## Purpose
The CI pipeline runs Trivy container image scans on every pull request and merge to main to block releases with known CRITICAL vulnerabilities in the API and web images.

## Scope
- Images scanned: `cleanwithsnapshot-api:ci` and `cleanwithsnapshot-web:ci` built from the repo Dockerfiles.
- Severity gate: **CRITICAL** only.
- Reports: JSON and SARIF artifacts are uploaded for every run.
- SBOMs: SPDX JSON SBOMs are generated for each image on every CI run and uploaded as CI artifacts.

## CI Behavior
- The Trivy job builds the API and web images and runs `trivy image` with `--severity CRITICAL --exit-code 1`.
- Any CRITICAL finding fails the job, which blocks the PR merge.
- Reports are always uploaded as artifacts, even when the scan fails.
- SBOM artifacts are stored in the `trivy-reports` artifact (`sbom-trivy-cleanwithsnapshot-*.json`) and retained for **30 days**.

## Trivy Ignore Policy
The default posture is to **not** use `.trivyignore`. If an ignore file is required, it must:
1. Include a brief justification per ignored finding.
2. Include an expiry date (YYYY-MM-DD) after which the ignore must be removed or renewed with updated justification.
3. Be reviewed by security owners as part of the PR.

## Ownership
Security and platform owners are responsible for maintaining the policy and reviewing any ignore file additions.
