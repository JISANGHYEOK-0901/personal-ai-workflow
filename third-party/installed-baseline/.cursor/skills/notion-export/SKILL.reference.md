---
name: notion-export
description: Resource-complete Notion backup/export using script-based recursive Notion Export zip automation. Use when backing up, exporting, downloading, archiving, or recursively saving Notion pages with images, files, attachments, resources, teaching materials, token_v2, file_token, Notion CLI, ntn, file:// image refs, subpages, or empty signedUrls. Always prefer the token_v2 + file_token export scripts over per-file getSignedFileUrls.
---

# Notion Export Skill

## Core Rule

For Notion backups where images, files, attachments, or lesson resources matter, use the recursive Export zip scripts first.

Do not start with `getSignedFileUrls`. The known failure mode is `HTTP 200` with empty `signedUrls`; repeated retries waste time.

## Prerequisites

- `bash` and `python3` on `PATH`.
- A Notion browser session that can open the target page.
- `token_v2` and `file_token` from the same browser profile/account.
- Optional local secret backend: macOS Keychain, Linux `secret-tool`, or chmod 600 file fallback.

The scripts run from the user's workspace and expect to live in `<workspace>/scripts/`. Each script `cd`s to the workspace root and writes exports there.

### Install or Refresh Scripts

If `<workspace>/scripts/` does not contain the latest export scripts, fetch them from this skill repo:

```bash
cd <your-workspace>
mkdir -p scripts
base=https://raw.githubusercontent.com/wild-mental/notion-export-skill/main/scripts
for f in notion_export_secrets.sh save_notion_export_cookies.sh export_with_token_v2.sh \
         export_notion_zip_token_v2.py check_token_v2_access.sh \
         check_token_v2_block_access.py check_notion_asset_auth.py \
         backup_with_token_v2.sh download_notion_page.py; do
  curl -fsSL "$base/$f" -o "scripts/$f"
done
chmod +x scripts/*.sh scripts/*.py
```

## Standard Command

First-time setup or cookie refresh:

```bash
cd <your-workspace>
./scripts/save_notion_export_cookies.sh
```

Then run an export:

```bash
./scripts/export_with_token_v2.sh "<Notion URL or page_id>"
```

The page argument is required. Pass a Notion URL, a 32-character page ID, or a hyphenated UUID page ID.

Before starting the export, `export_with_token_v2.sh` checks whether both `token_v2` and `file_token` are available.

```text
1. NOTION_TOKEN_V2 / NOTION_FILE_TOKEN environment variables
2. local secret backend
```

If either token is missing, the export script exits before starting the Notion task. Tell the user to run the local storage script in their terminal, then retry the export:

```bash
./scripts/save_notion_export_cookies.sh
```

The export script does not prompt for cookie values. The user must enter cookie values only through `save_notion_export_cookies.sh` or provide both environment variables for that run. Never ask them to paste these secrets into chat.

## Secret Backend

Backend selection:

```text
NOTION_SECRET_BACKEND=auto        # default
auto on macOS                     # macOS Keychain via security
auto on Linux with secret-tool     # libsecret / GNOME Keyring
auto otherwise                    # chmod 600 local file fallback after confirmation
NOTION_SECRET_BACKEND=keychain     # force macOS Keychain
NOTION_SECRET_BACKEND=secret-tool  # force Linux secret-tool
NOTION_SECRET_BACKEND=file         # force local chmod 600 file fallback
NOTION_SECRET_BACKEND=none         # never save; export requires both env vars
```

Default secret names:

```text
notion-export-token-v2
notion-export-file-token
account: notion-export
```

File fallback path:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/notion-export/cookies.env
```

The file fallback stores base64-encoded values in a chmod 600 file. It is not encrypted at rest, so the storage script asks for confirmation unless `NOTION_ALLOW_PLAINTEXT_STORE=1` is set.

## Bundled Scripts

| Script | Role |
|--------|------|
| `notion_export_secrets.sh` | Shared secret backend selection, read, save, and cookie normalization |
| `save_notion_export_cookies.sh` | Store `token_v2` + `file_token` in the selected local secret backend |
| `export_with_token_v2.sh` | Main entry: credential load, preflight, recursive export zip |
| `export_notion_zip_token_v2.py` | Enqueue, poll, download, and safely unzip the Notion export |
| `check_token_v2_access.sh` | Diagnose `token_v2` page access |
| `check_token_v2_block_access.py` | Per-origin block-access report |
| `check_notion_asset_auth.py` | Probe legacy `getSignedFileUrls` |
| `backup_with_token_v2.sh` | Legacy markdown-graph backup entry |
| `download_notion_page.py` | Legacy recursive markdown + asset downloader |

Prefer running the workspace `scripts/` copies because they write exports and summaries into the workspace.

## Cookie Rules

- `token_v2` and `file_token` are full browser-session secrets.
- Collect them only through the storage script's hidden terminal prompts.
- Do not print, log, or commit them.
- Store them only in a local secret backend after explicit user action/confirmation.
- Prefer macOS Keychain or Linux `secret-tool`; use file fallback only when the user accepts plaintext-at-rest risk.
- Use cookies from the same browser profile and Notion account that can open the target page.
- If copied as `token_v2=...`, `file_token=...`, or from a full `Cookie:` header, the scripts normalize the value.

Cookie lookup:

1. Open the target Notion page in the browser account with access.
2. Open DevTools.
3. Go to `Application > Storage > Cookies`.
4. Check `https://www.notion.so` and `https://app.notion.com`.
5. Copy `token_v2`.
6. Copy `file_token` from the same browser profile/account.

## Access Diagnostic

If export fails with `User cannot access block`, verify the browser session:

```bash
cd <your-workspace>
./scripts/check_token_v2_access.sh "<Notion URL or page_id>"
```

Good result:

```json
"role": "reader" | "editor",
"has_value": true,
"matches_page": true
```

Bad result:

```json
"role": "none",
"has_value": false,
"root_present": false
```

If bad, the user copied cookies from the wrong account/profile or the account does not have access to the page.

If only `app.notion.com` works, retry export with:

```bash
NOTION_API_ORIGIN=https://app.notion.com ./scripts/export_with_token_v2.sh "<Notion URL or page_id>"
```

## Export Flow

The main export script:

1. Normalizes the Notion page URL/page ID to a 32-char page ID.
2. Uses `token_v2 + file_token`.
3. Enqueues a Notion internal `exportBlock` task.
4. Polls `getTasks` until an export zip URL appears.
5. Downloads the zip with `token_v2 + file_token`, `X-Notion-Space-Id`, and `Referer`.
6. Saves and safely unzips under `notion-exports/`.

During unzip, zip member paths are repeatedly URL-decoded and Unicode NFC normalized. Path components that exceed `NOTION_EXPORT_MAX_FILENAME_BYTES` (default 240 bytes), or relative paths that exceed `NOTION_EXPORT_MAX_RELATIVE_PATH_BYTES` (default 700 bytes), are shortened by UTF-8 byte length and get a stable hash suffix. The original zip is preserved unchanged.

Local links inside extracted Markdown files are rewritten to the actual extracted paths as angle-bracket local targets such as `[title](<decoded path/file.md>)`, instead of percent-encoded URL-style targets. This keeps links compatible with Cursor Markdown Preview and other resolvers that do not URL-decode local Markdown link targets.

Expected success output:

```json
{
  "zip": "notion-exports/notion-export-....zip",
  "bytes": 123456,
  "unzipped": "notion-exports/notion-export-...",
  "unzip": {
    "extracted_files": 42,
    "normalized_paths": 3,
    "shortened_paths": 1,
    "collisions": 0,
    "rewritten_links": 2
  }
}
```

Use `--unzip-only` to safely re-extract an existing zip without calling Notion:

```bash
python3 scripts/export_notion_zip_token_v2.py --unzip-only notion-exports/notion-export-....zip --out-dir notion-exports/notion-export-...-safe
```

## Common Failures

### `signed_present: 0`, `signed_empty: 20`

Old per-file signing is failing. Switch to Export zip. Do not keep retrying `getSignedFileUrls`.

### `User cannot access block`

Run `check_token_v2_access.sh`. If role is `none`, get cookies from the correct browser account/profile.

If stored cookies are stale, refresh them:

```bash
./scripts/save_notion_export_cookies.sh
```

### Zip download `HTTP 403` with HTML

Check the **download URL host first**. This is usually not an expired cookie.

1. Notion serves export zips from `file.notion.com` / `file.notion.so`. If the request to
   those hosts goes out **without a `Cookie` header**, that is a host-matching bug in the
   downloader, not a credential problem. `export_notion_zip_token_v2.py` matches by parsed
   hostname (`is_notion_host()`); a substring test like `"notion.so/" in url` silently
   misses `file.notion.com` and 403s every download.
2. If `check_token_v2_access.sh` reports `role=editor` and only the zip 403s, refreshing
   cookies is almost always wasted effort. Confirm the `Cookie` header is actually being
   sent before suspecting expiry.
3. Only after the host check, verify `file_token` comes from the same profile/account as
   `token_v2`.

The downloader must send these to Notion-owned hosts:

```text
Cookie: token_v2=...;file_token=...
X-Notion-Space-Id: <space-id>
Referer: https://www.notion.so/
```

S3 pre-signed URLs (`*.amazonaws.com`) must **not** get these headers — cookies break
signature validation. Never widen the host match to cover them.

### `file_token` missing

Refresh the target Notion page, then re-check cookies on both `www.notion.so` and `app.notion.com`.

### `Could not infer spaceId`

`infer_space_id()` scans `.notion-cache/*.md`, so a workspace that never ran the legacy
Markdown path has nothing to scan. The script then falls back to `getRecordValues`, which
returns the page's own `space_id` and prints `spaceId resolved via getRecordValues: ...`.

If both paths fail, read the value directly and pass it in:

```bash
python3 scripts/check_token_v2_block_access.py "<Notion URL or page_id>"
# read origins[].getRecordValues.space_id from the report

NOTION_SPACE_ID=<space-id> ./scripts/export_with_token_v2.sh "<Notion URL or page_id>"
```

A populated `origins[].getRecordValues.space_id` alongside a failed inference means only
the local cache scan came up empty — the value is valid, just not discoverable from files.

## Legacy Markdown Path

Use only after resource-complete export is secured, or when the user explicitly wants local Markdown graph processing:

```bash
python3 scripts/download_notion_page.py "<Notion URL or page_id>"
```

Known behavior:

- `.notion-cache/<page_id>.md` avoids re-fetching pages.
- `.notion-assets.json` records `source -> local file` after successful asset downloads.
- Re-runs skip existing non-empty asset files.
- `file://` refs and empty signed URLs mean this path is not resource-complete.

## Reporting

For export zip backups, report:

```text
- Export zip path
- Extracted folder path
- Zip size
- Whether access diagnostics were needed
- Any remaining manual step
```

## 스킬 발견 (Cursor)

| 위치 | 경로 |
|------|------|
| 프로젝트 | `.cursor/skills/notion-export/SKILL.md` |
| 개인 | `~/.cursor/skills/notion-export/SKILL.md` |

개인 스킬 `~/.cursor/skills/` 생성 후 UI에 안 보이면 Reload Window가 필요할 수 있다. 수동 호출: `/notion-export`.
