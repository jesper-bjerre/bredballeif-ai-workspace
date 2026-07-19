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

exec python3 -m agent "$@"
