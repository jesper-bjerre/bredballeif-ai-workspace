#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
case "${1:-}" in
  -h|--help)
    echo "Brug: bredballeif-oekonomi.sh budget-report --department <afdeling> [--year YYYY] [--years 1..3]"
    exit 0
    ;;
  budget-report) ;;
  *)
    echo "Afvist: økonomi-wrapperen tillader kun read-only budget-report." >&2
    exit 2
    ;;
esac
exec bash "$SKILLS_DIR/bredballeif-padel-conventus/bin/bredballeif-padel-conventus.sh" "$@"
