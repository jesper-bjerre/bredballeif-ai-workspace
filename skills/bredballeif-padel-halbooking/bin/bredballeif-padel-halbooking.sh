#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="$SKILL_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}"

case "${1:-}" in
  -h|--help|search|history|availability) ;;
  "")
    echo "Brug: bredballeif-padel-halbooking.sh <search|history|availability> [argumenter]" >&2
    exit 2
    ;;
  *)
    echo "Afvist: standard-wrapperen tillader kun read-only HalBooking-actions." >&2
    exit 2
    ;;
esac

exec python3 -m agent "$@"
