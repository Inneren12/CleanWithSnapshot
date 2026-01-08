#!/usr/bin/env bash
set -euo pipefail

python scripts/build_tokens.py

git diff --exit-code -- web/app/styles/tokens.css
