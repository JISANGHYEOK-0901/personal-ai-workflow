#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=scripts/notion_export_secrets.sh
source "$ROOT_DIR/scripts/notion_export_secrets.sh"

notion_export_require_page_arg "$0" "$@" || exit $?
PAGE_ID="$1"

preflight_token_access() {
  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/notion-token-access.XXXXXX.json")"
  if ! python3 scripts/check_token_v2_block_access.py "$PAGE_ID" > "$tmp"; then
    cat "$tmp" >&2 || true
    rm -f "$tmp"
    return 1
  fi
  if python3 - "$tmp" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
for origin in data.get("origins", []):
    record = origin.get("getRecordValues", {})
    if record.get("has_value") and record.get("matches_page") and record.get("role") != "none":
        print(f"token_v2 access ok: {origin.get('origin')} role={record.get('role')}", file=sys.stderr)
        raise SystemExit(0)
print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
raise SystemExit(1)
PY
  then
    rm -f "$tmp"
    return 0
  fi
  rm -f "$tmp"
  return 1
}

notion_export_require_stored_export_cookies || exit $?

if ! preflight_token_access; then
  notion_export_print_cookie_setup_instructions \
    "token_v2 access preflight failed. Refresh cookies from the browser profile/account that can open this page."
  exit 1
fi

python3 scripts/export_notion_zip_token_v2.py "$PAGE_ID" --type markdown
