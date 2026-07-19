#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

case "${1:-}" in
  -h|--help|discover|create|onboard|export|welcome-email|process-emails|book-court) ;;
  *)
    echo "Afvist: admin-wrapperen tillader kun godkendelsespligtige onboarding-actions." >&2
    exit 2
    ;;
esac

export PYTHONPATH="$SKILL_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m agent "$@"
