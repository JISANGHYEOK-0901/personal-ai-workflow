#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = ROOT / "scripts" / "download_notion_page.py"
DEFAULT_ORIGINS = [
    "https://www.notion.so",
    "https://www.notion.com",
    "https://app.notion.com",
]


def load_download_module():
    spec = importlib.util.spec_from_file_location("download_notion_page", DOWNLOAD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("Could not load download_notion_page.py")
    spec.loader.exec_module(module)
    return module


def hyphenated_uuid(value: str) -> str:
    return str(uuid.UUID(value))


def infer_space_id(d) -> Optional[str]:
    explicit = os.environ.get("NOTION_SPACE_ID", "").strip()
    if explicit:
        return explicit
    for path in sorted((ROOT / ".notion-cache").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        matches = list(d.IMAGE_RE.finditer(text)) + list(d.FILE_RE.finditer(text))
        for match in matches:
            file_url = match.group(2) if match.re is d.IMAGE_RE else match.group(1)
            try:
                ref = d.parse_image_ref(file_url)
            except Exception:
                continue
            space_id = ref.get("permissionRecord", {}).get("spaceId")
            if space_id:
                return space_id
    return None


def post_json(origin: str, endpoint: str, payload: dict, token_v2: str, space_id: Optional[str]) -> dict:
    headers = {
        "Cookie": f"token_v2={token_v2}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    if space_id:
        headers["X-Notion-Space-Id"] = space_id
    req = urllib.request.Request(
        f"{origin.rstrip('/')}/api/v3/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def summarize_get_record(body: dict, page_uuid: str) -> dict:
    results = body.get("results") or []
    first = results[0] if results else {}
    value = first.get("value") or {}
    return {
        "result_count": len(results),
        "role": first.get("role"),
        "has_value": bool(value),
        "value_type": value.get("type"),
        "space_id": value.get("space_id"),
        "parent_table": value.get("parent_table"),
        "matches_page": value.get("id") == page_uuid,
    }


def summarize_load_page_chunk(body: dict, page_uuid: str) -> dict:
    block_map = body.get("recordMap", {}).get("block", {})
    root = block_map.get(page_uuid, {})
    value = root.get("value") or {}
    return {
        "block_count": len(block_map),
        "root_present": bool(value),
        "root_type": value.get("type"),
        "root_space_id": value.get("space_id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether token_v2 can read the Notion root block.",
        usage='%(prog)s "<Notion URL or page_id>"',
    )
    parser.add_argument("page", metavar="PAGE", help="Notion page URL or page ID")
    args = parser.parse_args()

    d = load_download_module()
    try:
        page_id = d.normalize_page_id(args.page)
    except ValueError as exc:
        parser.error(str(exc))

    token_v2 = d.normalize_token_v2(os.environ.get("NOTION_TOKEN_V2", ""))
    if not token_v2:
        raise SystemExit("NOTION_TOKEN_V2 is empty")

    page_uuid = hyphenated_uuid(page_id)
    space_id = infer_space_id(d)
    origins = [item.strip().rstrip("/") for item in os.environ.get("NOTION_API_ORIGINS", "").split(",") if item.strip()]
    if not origins:
        origins = DEFAULT_ORIGINS

    report = {
        "page": page_uuid,
        "space_id": space_id,
        "origins": [],
    }

    for origin in origins:
        item = {"origin": origin}
        try:
            body = post_json(
                origin,
                "getRecordValues",
                {"requests": [{"id": page_uuid, "table": "block", "version": -1}]},
                token_v2,
                space_id,
            )
            item["getRecordValues"] = summarize_get_record(body, page_uuid)
        except urllib.error.HTTPError as exc:
            item["getRecordValues"] = {"http_error": exc.code}
        except Exception as exc:
            item["getRecordValues"] = {"error": type(exc).__name__}

        try:
            body = post_json(
                origin,
                "loadPageChunk",
                {
                    "pageId": page_uuid,
                    "limit": 20,
                    "cursor": {"stack": []},
                    "chunkNumber": 0,
                    "verticalColumns": False,
                },
                token_v2,
                space_id,
            )
            item["loadPageChunk"] = summarize_load_page_chunk(body, page_uuid)
        except urllib.error.HTTPError as exc:
            item["loadPageChunk"] = {"http_error": exc.code}
        except Exception as exc:
            item["loadPageChunk"] = {"error": type(exc).__name__}

        report["origins"].append(item)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
