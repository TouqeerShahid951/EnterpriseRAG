#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uv run --project "$ROOT_DIR/backend" --extra dev \
  ruff check \
  "$ROOT_DIR/backend/src" \
  "$ROOT_DIR/backend/apps" \
  "$ROOT_DIR/backend/tests" \
  "$ROOT_DIR/deployment-controller" \
  "$ROOT_DIR/scripts" \
  --select F401,F811,F841

uv run --project "$ROOT_DIR/backend" --extra dev \
  vulture \
  "$ROOT_DIR/backend/src" \
  "$ROOT_DIR/backend/apps" \
  "$ROOT_DIR/deployment-controller" \
  "$ROOT_DIR/scripts" \
  --exclude '*/tests/*,*/._*.py' \
  --min-confidence 80

npm --prefix "$ROOT_DIR/frontend" run check:dead-code
