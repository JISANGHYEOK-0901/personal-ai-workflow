#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=scripts/notion_export_secrets.sh
source "$ROOT_DIR/scripts/notion_export_secrets.sh"

notion_export_require_page_arg "$0" "$@" || exit $?
PAGE_ID="$1"

notion_export_require_stored_token_v2 || exit $?
python3 scripts/check_notion_asset_auth.py
python3 scripts/download_notion_page.py "$PAGE_ID"
