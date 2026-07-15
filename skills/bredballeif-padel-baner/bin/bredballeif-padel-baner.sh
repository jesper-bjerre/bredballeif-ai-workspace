#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  export PYTHONPATH="$SKILL_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}"
  exec python3 -m agent --help
fi

if [[ $# -lt 1 ]]; then
  echo "Brug: bredballeif-padel-baner.sh DD-MM-YYYY [HH:MM-fra] [HH:MM-til]" >&2
  exit 2
fi

DATE="$1"
FROM="${2:-}"
TO="${3:-}"

if [[ ! "$DATE" =~ ^[0-9]{2}-[0-9]{2}-[0-9]{4}$ ]]; then
  echo "Fejl: dato skal være DD-MM-YYYY (fik: '$DATE')" >&2
  exit 2
fi

args=(availability --date "$DATE")
[[ -n "$FROM" ]] && args+=(--time-from "$FROM")
[[ -n "$TO" ]] && args+=(--time-to "$TO")

exec python3 -m agent "${args[@]}"
