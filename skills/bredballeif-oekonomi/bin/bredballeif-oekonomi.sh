#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
case "${1:-}" in
  -h|--help)
    echo "Brug: bredballeif-oekonomi.sh budget-report --department <afdeling> [--year YYYY] [--years 1..3]"
    echo "     bredballeif-oekonomi.sh board-report [--year YYYY] --output <privat-fil.pdf>"
    exit 0
    ;;
  budget-report) ;;
  board-report)
    WORKSPACE_DIR="$(cd -- "$SKILLS_DIR/.." && pwd)"
    export PYTHONPATH="$SCRIPT_DIR/../scripts${PYTHONPATH:+:$PYTHONPATH}"
    if [[ -n "${BIF_PYTHON_BIN:-}" ]]; then
      PYTHON_BIN="$BIF_PYTHON_BIN"
    elif [[ -x "$WORKSPACE_DIR/.venv/bin/python" ]]; then
      PYTHON_BIN="$WORKSPACE_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
      PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1; then
      PYTHON_BIN="python"
    else
      echo "Python mangler; installer økonomi-skillens requirements i runtime." >&2
      exit 1
    fi
    exec "$PYTHON_BIN" -m bif_economy "$@"
    ;;
  *)
    echo "Afvist: økonomi-wrapperen tillader kun budget-report og board-report." >&2
    exit 2
    ;;
esac
exec bash "$SKILLS_DIR/bredballeif-padel-conventus/bin/bredballeif-padel-conventus.sh" "$@"
