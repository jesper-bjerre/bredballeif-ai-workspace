#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

case "${1:-}" in
  -h|--help|create-americano|create-mexicano|create-group) ;;
  *)
    echo "Afvist: admin-wrapperen tillader kun Conventus write-actions og kræver gatewayapproval." >&2
    exit 2
    ;;
esac

export PYTHONPATH="$SKILL_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m agent "$@"
