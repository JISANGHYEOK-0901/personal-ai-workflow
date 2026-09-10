#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/notion_export_secrets.sh
source "$SCRIPT_DIR/notion_export_secrets.sh"

token_v2="$(notion_export_prompt_secret "NOTION_TOKEN_V2: ")"
file_token="$(notion_export_prompt_secret "NOTION_FILE_TOKEN: ")"

token_v2="$(notion_export_normalize_cookie_value "$token_v2" "token_v2")"
file_token="$(notion_export_normalize_cookie_value "$file_token" "file_token")"

if [[ -z "$token_v2" || -z "$file_token" ]]; then
  echo "Both NOTION_TOKEN_V2 and NOTION_FILE_TOKEN are required." >&2
  exit 1
fi

notion_export_save_credentials "$token_v2" "$file_token"
