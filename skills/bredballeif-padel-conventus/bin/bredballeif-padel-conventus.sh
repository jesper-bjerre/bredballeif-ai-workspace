#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="$SKILL_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-}" in
  -h|--help|search|list|stats|compare|budget-report) ;;
  "")
    echo "Brug: bredballeif-padel-conventus.sh <search|list|stats|compare|budget-report> [argumenter]" >&2
    exit 2
    ;;
  *)
    echo "Afvist: standard-wrapperen tillader kun read-only Conventus-actions." >&2
    exit 2
    ;;
esac

# Prefer the workspace environment even when OpenClaw has not activated it.
WORKSPACE_DIR="$(cd -- "$SKILL_DIR/../.." && pwd)"
if [[ -n "${BIF_PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$BIF_PYTHON_BIN"
elif [[ -x "$WORKSPACE_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$WORKSPACE_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Fejl: Python mangler. Opret workspace .venv og installer skillens requirements." >&2
  exit 1
fi
exec "$PYTHON_BIN" -m agent "$@"
