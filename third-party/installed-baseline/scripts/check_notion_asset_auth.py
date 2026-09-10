#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = ROOT / "scripts" / "download_notion_page.py"


def load_export_module():
    spec = importlib.util.spec_from_file_location("download_notion_page", EXPORT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("Could not load download_notion_page.py")
    spec.loader.exec_module(module)
    return module


def sample_refs(d, limit: int = 20) -> list[dict]:
    refs = []
    seen = set()
    for path in sorted((ROOT / ".notion-cache").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        matches = list(d.IMAGE_RE.finditer(text)) + list(d.FILE_RE.finditer(text))
        for match in matches:
            file_url = match.group(2) if match.re is d.IMAGE_RE else match.group(1)
            try:
                ref = d.parse_image_ref(file_url)
            except Exception:
                continue
            source = ref.get("source")
            if not source or source in seen:
                continue
            seen.add(source)
            refs.append(ref)
            if len(refs) >= limit:
                return refs
    return refs


def main() -> int:
    d = load_export_module()
    token = d.normalize_token_v2(os.environ.get("NOTION_TOKEN_V2", ""))
    if not token:
        print(json.dumps({"ok": False, "error": "NOTION_TOKEN_V2 is empty"}, indent=2))
        return 1

    refs = sample_refs(d)
    if not refs:
        print(json.dumps({"ok": False, "error": "No cached file refs found"}, indent=2))
        return 1

    summary = {
        "ok": False,
        "tested": 0,
        "http_200": 0,
        "signed_present": 0,
        "signed_empty": 0,
        "http_errors": {},
        "exceptions": 0,
    }

    for ref in refs:
        payload = {
            "urls": [
                {
                    "url": ref["source"],
                    "permissionRecord": ref["permissionRecord"],
                }
            ]
        }
        req = urllib.request.Request(
            "https://www.notion.so/api/v3/getSignedFileUrls",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Cookie": f"token_v2={token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        summary["tested"] += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.load(resp)
                signed = d.extract_signed_url(body)
                summary["http_200"] += int(resp.status == 200)
                if signed:
                    summary["signed_present"] += 1
                else:
                    summary["signed_empty"] += 1
        except urllib.error.HTTPError as exc:
            code = str(exc.code)
            summary["http_errors"][code] = summary["http_errors"].get(code, 0) + 1
        except Exception:
            summary["exceptions"] += 1
        time.sleep(0.05)

    summary["ok"] = summary["signed_present"] > 0
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
