#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = ROOT / "scripts" / "download_notion_page.py"
EXPORT_DIR = ROOT / "notion-exports"
API_ORIGIN = os.environ.get("NOTION_API_ORIGIN", "https://www.notion.so").rstrip("/")
MAX_FILENAME_BYTES = int(os.environ.get("NOTION_EXPORT_MAX_FILENAME_BYTES", "240"))
MAX_RELATIVE_PATH_BYTES = int(os.environ.get("NOTION_EXPORT_MAX_RELATIVE_PATH_BYTES", "700"))
MIN_PATH_COMPONENT_BYTES = 48
LINK_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


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


def normalize_cookie_value(value: str, name: str) -> str:
    value = value.strip().strip("'\"")
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()

    prefix = f"{name}="
    for part in value.split(";"):
        part = part.strip()
        if part.startswith(prefix):
            return part.split("=", 1)[1].strip().strip("'\"")

    if value.startswith(prefix):
        return value.split("=", 1)[1].strip().strip("'\"")
    return value


def notion_headers(token_v2: str, file_token: str, space_id: str) -> Dict[str, str]:
    headers = {
        "Cookie": f"token_v2={token_v2};file_token={file_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    # The space-id header is what we are trying to discover in fetch_space_id_via_record_values(),
    # so send it only when known. An empty header value is worse than no header.
    if space_id:
        headers["X-Notion-Space-Id"] = space_id
    return headers


def post_json(endpoint: str, payload: dict, token_v2: str, file_token: str, space_id: str) -> dict:
    req = urllib.request.Request(
        f"{API_ORIGIN}/api/v3/{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers=notion_headers(token_v2, file_token, space_id),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"{API_ORIGIN}/api/v3/{endpoint} failed: HTTP {exc.code}: {body}") from exc


def fetch_space_id_via_record_values(page_id: str, token_v2: str, file_token: str) -> Optional[str]:
    """Read the page's own space_id from the API.

    infer_space_id() only scans .notion-cache/*.md, so a workspace that never ran the
    legacy Markdown path has nothing to scan and inference fails even though the API
    reports space_id fine. This is the same value check_token_v2_block_access.py prints
    as origins[].getRecordValues.space_id.
    """
    payload = {"requests": [{"table": "block", "id": hyphenated_uuid(page_id), "version": -1}]}
    try:
        body = post_json("getRecordValues", payload, token_v2, file_token, "")
    except (RuntimeError, urllib.error.URLError, ValueError):
        return None

    for result in body.get("results") or []:
        if not isinstance(result, dict):
            continue
        value = result.get("value")
        if isinstance(value, dict):
            space_id = value.get("space_id")
            if space_id:
                return str(space_id)
    return None


def find_first_export_url(value) -> Optional[str]:
    if isinstance(value, dict):
        preferred_keys = ("exportURL", "exportUrl", "url")
        for key in preferred_keys:
            item = value.get(key)
            if isinstance(item, str) and item.startswith(("http://", "https://")):
                return item
        for item in value.values():
            found = find_first_export_url(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_first_export_url(item)
            if found:
                return found
    elif isinstance(value, str):
        if value.startswith(("http://", "https://")) and ".zip" in value:
            return value
    return None


def enqueue_export(page_id: str, space_id: str, token_v2: str, file_token: str, export_type: str) -> str:
    payload = {
        "task": {
            "eventName": "exportBlock",
            "request": {
                "block": {
                    "id": hyphenated_uuid(page_id),
                },
                "recursive": True,
                "shouldExportComments": False,
                "exportOptions": {
                    "exportType": export_type,
                    "timeZone": "Asia/Seoul",
                    "locale": "ko-KR",
                    "collectionViewExportType": "all",
                    "preferredViewMap": {},
                },
            },
        }
    }
    body = post_json("enqueueTask", payload, token_v2, file_token, space_id)
    task_id = body.get("taskId") or body.get("id")
    if not task_id:
        raise RuntimeError(f"Could not find taskId in enqueueTask response: {body}")
    return task_id


def wait_for_export_url(
    task_id: str,
    space_id: str,
    token_v2: str,
    file_token: str,
    timeout_seconds: int,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_body = None
    while time.monotonic() < deadline:
        body = post_json("getTasks", {"taskIds": [task_id]}, token_v2, file_token, space_id)
        last_body = body
        export_url = find_first_export_url(body)
        if export_url:
            return export_url

        task = None
        if isinstance(body.get("results"), list):
            task = next((item for item in body["results"] if item.get("id") == task_id), None)
        state = task.get("state") if isinstance(task, dict) else None
        if state not in {"in_progress", "not_started", None}:
            raise RuntimeError(
                "Export task failed: "
                + json.dumps(body, ensure_ascii=False)[:1000]
            )

        print("waiting for Notion export task ...", file=sys.stderr)
        time.sleep(3)

    raise TimeoutError(
        "Timed out waiting for Notion export URL. Last response: "
        + json.dumps(last_body, ensure_ascii=False)[:1000]
    )


def is_notion_host(url: str) -> bool:
    # Notion issues export zips and protected assets from notion.so AND notion.com
    # hosts (e.g. file.notion.com, app.notion.com). A bare "notion.so/" substring
    # check misses file.notion.com, so the file_token cookie / space-id header are
    # not attached and the download 403s. S3 pre-signed URLs (amazonaws.com) are
    # intentionally NOT matched (they need no Notion auth headers).
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return (
        host == "notion.so"
        or host.endswith(".notion.so")
        or host == "notion.com"
        or host.endswith(".notion.com")
    )


def download_url(url: str, dest: Path, token_v2: str, file_token: str, space_id: str) -> None:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.notion.so/",
    }
    if is_notion_host(url):
        headers["Cookie"] = f"token_v2={token_v2};file_token={file_token}"
        headers["X-Notion-Space-Id"] = space_id
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            dest.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"Download failed: HTTP {exc.code}: {body}") from exc


def byte_len(value: str) -> int:
    return len(value.encode("utf-8"))


def unquote_repeated(value: str, rounds: int = 5) -> str:
    result = value
    for _ in range(rounds):
        decoded = urllib.parse.unquote(result)
        if decoded == result:
            break
        result = decoded
    return unicodedata.normalize("NFC", result)


def truncate_utf8(value: str, max_bytes: int) -> str:
    if byte_len(value) <= max_bytes:
        return value
    return value.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")


def split_extension(value: str) -> Tuple[str, str]:
    stem, dot, suffix = value.rpartition(".")
    if not dot or not stem:
        return value, ""
    suffix = dot + suffix
    if byte_len(suffix) > 32:
        return value, ""
    return stem, suffix


def shorten_component(value: str, limit: int = MAX_FILENAME_BYTES) -> str:
    if byte_len(value) <= limit:
        return value

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    stem, suffix = split_extension(value)
    trailer = f"-{digest}{suffix}"
    stem_limit = max(1, limit - byte_len(trailer))
    stem = truncate_utf8(stem, stem_limit).rstrip(" .") or "file"
    shortened = f"{stem}-{digest}{suffix}"
    if byte_len(shortened) <= limit:
        return shortened

    fallback = f"{digest}{suffix}"
    if byte_len(fallback) <= limit:
        return fallback
    return truncate_utf8(digest, limit)


def validate_zip_member_name(member_name: str) -> None:
    name = member_name.replace("\\", "/")
    first_part = name.split("/", 1)[0]
    if name.startswith("/") or (len(first_part) == 2 and first_part[1] == ":" and first_part[0].isalpha()):
        raise RuntimeError(f"Refusing to extract unsafe zip member path: {member_name}")


def safe_component(raw: str, shorten: bool) -> str:
    value = unquote_repeated(raw).replace("\x00", "_").replace("/", "_")
    if value in {"", "."}:
        return "_"
    if value == "..":
        value = "__"
    if shorten:
        value = shorten_component(value)
    return value


def zip_rel_parts(name: str, shorten: bool) -> List[str]:
    validate_zip_member_name(name)
    parts = []
    for raw in name.replace("\\", "/").split("/"):
        if not raw or raw == ".":
            continue
        parts.append(safe_component(raw, shorten=shorten))
    return parts


def shrink_relative_path(parts: List[str]) -> List[str]:
    safe_parts = list(parts)
    while byte_len("/".join(safe_parts)) > MAX_RELATIVE_PATH_BYTES:
        candidates = [
            (byte_len(part), index)
            for index, part in enumerate(safe_parts)
            if byte_len(part) > MIN_PATH_COMPONENT_BYTES
        ]
        if not candidates:
            raise RuntimeError(f"Could not shorten zip member path enough: {'/'.join(parts)}")

        current_bytes, index = max(candidates)
        overflow = byte_len("/".join(safe_parts)) - MAX_RELATIVE_PATH_BYTES
        next_limit = max(
            MIN_PATH_COMPONENT_BYTES,
            current_bytes - min(current_bytes - MIN_PATH_COMPONENT_BYTES, overflow + 8),
        )
        safe_parts[index] = shorten_component(safe_parts[index], next_limit)
    return safe_parts


def add_collision_suffix(value: str, token: str) -> str:
    stem, suffix = split_extension(value)
    return shorten_component(f"{stem}-{token}{suffix}")


def unique_safe_rel(safe_rel: str, original_name: str, used: Set[str]) -> Tuple[str, bool]:
    if safe_rel not in used:
        used.add(safe_rel)
        return safe_rel, False

    parts = safe_rel.split("/")
    original_last = parts[-1]
    digest = hashlib.sha1(original_name.encode("utf-8")).hexdigest()[:8]
    index = 2
    while True:
        parts[-1] = add_collision_suffix(original_last, f"{digest}-{index}")
        candidate = "/".join(parts)
        if candidate not in used:
            used.add(candidate)
            return candidate, True
        index += 1


def build_extraction_plan(archive: zipfile.ZipFile):
    plan = []
    decoded_to_safe = {}  # type: Dict[str, str]
    safe_to_decoded = {}  # type: Dict[str, str]
    used = set()  # type: Set[str]
    stats = {
        "extracted_files": 0,
        "normalized_paths": 0,
        "shortened_paths": 0,
        "collisions": 0,
        "rewritten_links": 0,
    }

    for info in archive.infolist():
        if info.is_dir():
            continue

        raw_parts = [part for part in info.filename.replace("\\", "/").split("/") if part and part != "."]
        decoded_parts = zip_rel_parts(info.filename, shorten=False)
        safe_parts = shrink_relative_path(zip_rel_parts(info.filename, shorten=True))
        if not safe_parts:
            continue

        raw_rel = "/".join(raw_parts)
        decoded_rel = "/".join(decoded_parts)
        safe_rel = "/".join(safe_parts)
        if raw_rel != decoded_rel:
            stats["normalized_paths"] += 1
        if decoded_rel != safe_rel:
            stats["shortened_paths"] += 1

        safe_rel, collided = unique_safe_rel(safe_rel, info.filename, used)
        if collided:
            stats["collisions"] += 1

        plan.append((info, decoded_rel, safe_rel))
        decoded_to_safe.setdefault(decoded_rel, safe_rel)
        safe_to_decoded[safe_rel] = decoded_rel
        stats["extracted_files"] += 1

    return plan, decoded_to_safe, safe_to_decoded, stats


def safe_extract_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, out_dir: Path, safe_rel: str) -> None:
    out_root = out_dir.resolve()
    target = out_dir.joinpath(*safe_rel.split("/"))
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(out_root)
    except ValueError as exc:
        raise RuntimeError(f"Unsafe zip member path: {info.filename}") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, target.open("wb") as dest:
        shutil.copyfileobj(source, dest)


def decode_link_path(value: str) -> str:
    parts = []
    for raw in value.replace("\\", "/").split("/"):
        if raw in {"", ".", ".."}:
            parts.append(raw)
        else:
            parts.append(unquote_repeated(raw).replace("\x00", "_").replace("/", "_"))
    return "/".join(parts)


def markdown_local_target(value: str, fragment: str = "") -> str:
    escaped = value.replace("<", "%3C").replace(">", "%3E")
    return f"<{escaped}{fragment}>"


def unwrap_markdown_target(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return stripped[1:-1]
    return stripped


def split_fragment(target: str) -> Tuple[str, str]:
    index = target.find("#")
    if index < 0:
        return target, ""
    return target[:index], target[index:]


def rewrite_target(
    target: str,
    md_safe_rel: str,
    md_decoded_rel: str,
    decoded_to_safe: Dict[str, str],
) -> str:
    stripped = unwrap_markdown_target(target)
    if not stripped or stripped.startswith("#") or stripped.startswith("//"):
        return target
    if LINK_SCHEME_RE.match(stripped):
        return target

    path_part, fragment = split_fragment(stripped)
    if not path_part or path_part.startswith("/"):
        return target

    decoded_path = decode_link_path(path_part)
    decoded_base = posixpath.dirname(md_decoded_rel)
    decoded_abs = posixpath.normpath(posixpath.join(decoded_base, decoded_path))
    safe_abs = decoded_to_safe.get(decoded_abs)
    if not safe_abs:
        return target

    safe_base = posixpath.dirname(md_safe_rel)
    safe_rel = posixpath.relpath(safe_abs, safe_base or ".")
    return markdown_local_target(safe_rel, fragment)


def rewrite_markdown_text(
    text: str,
    md_safe_rel: str,
    md_decoded_rel: str,
    decoded_to_safe: Dict[str, str],
) -> Tuple[str, int]:
    output = []
    index = 0
    rewritten = 0

    while True:
        start = text.find("](", index)
        if start < 0:
            output.append(text[index:])
            break

        target_start = start + 2
        if target_start < len(text) and text[target_start] == "<":
            angle_end = text.find(">", target_start + 1)
            line_end = text.find("\n", target_start)
            if angle_end >= 0 and (line_end < 0 or angle_end < line_end):
                close_index = angle_end + 1
                if close_index < len(text) and text[close_index] == ")":
                    target = text[target_start:close_index]
                    new_target = rewrite_target(target, md_safe_rel, md_decoded_rel, decoded_to_safe)
                    if new_target != target:
                        rewritten += 1
                    output.append(text[index:target_start])
                    output.append(new_target)
                    output.append(")")
                    index = close_index + 1
                    continue

        depth = 0
        cursor = target_start
        fallback_end = None
        accepted = None  # type: Optional[Tuple[int, str]]
        while cursor < len(text):
            char = text[cursor]
            if char == "\n":
                break
            if char == "\\":
                cursor += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                target = text[target_start:cursor]
                new_target = rewrite_target(target, md_safe_rel, md_decoded_rel, decoded_to_safe)
                if new_target != target:
                    accepted = (cursor, new_target)
                    break

                if depth == 0 and fallback_end is None:
                    next_char = text[cursor + 1] if cursor + 1 < len(text) else ""
                    target_is_external = bool(LINK_SCHEME_RE.match(target.strip()))
                    if target_is_external or next_char not in {"/", "%"}:
                        fallback_end = cursor
                elif depth > 0:
                    depth -= 1
            cursor += 1

        if accepted:
            cursor, new_target = accepted
            rewritten += 1
        elif fallback_end is not None:
            cursor = fallback_end
            target = text[target_start:cursor]
            new_target = rewrite_target(target, md_safe_rel, md_decoded_rel, decoded_to_safe)
            if new_target != target:
                rewritten += 1
        else:
            output.append(text[index:])
            break

        output.append(text[index:target_start])
        output.append(new_target)
        output.append(")")
        index = cursor + 1

    return "".join(output), rewritten


def rewrite_markdown_links(
    out_dir: Path,
    decoded_to_safe: Dict[str, str],
    safe_to_decoded: Dict[str, str],
) -> int:
    rewritten = 0
    for path in out_dir.rglob("*.md"):
        safe_rel = path.relative_to(out_dir).as_posix()
        decoded_rel = safe_to_decoded.get(safe_rel)
        if not decoded_rel:
            continue

        text = path.read_text(encoding="utf-8")
        new_text, count = rewrite_markdown_text(text, safe_rel, decoded_rel, decoded_to_safe)
        if count:
            path.write_text(new_text, encoding="utf-8")
            rewritten += count
    return rewritten


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def unzip(zip_path: Path, out_dir: Optional[Path] = None) -> Tuple[Path, Dict[str, int]]:
    if out_dir is None:
        out_dir = zip_path.with_suffix("")
    elif not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        plan, decoded_to_safe, safe_to_decoded, stats = build_extraction_plan(archive)
        for info, _decoded_rel, safe_rel in plan:
            safe_extract_member(archive, info, out_dir, safe_rel)

    stats["rewritten_links"] = rewrite_markdown_links(out_dir, decoded_to_safe, safe_to_decoded)
    print(
        "safe unzip: "
        f"extracted={stats['extracted_files']} "
        f"normalized={stats['normalized_paths']} "
        f"shortened={stats['shortened_paths']} "
        f"collisions={stats['collisions']} "
        f"rewritten_links={stats['rewritten_links']}",
        file=sys.stderr,
    )
    return out_dir, stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Request a Notion recursive export zip with token_v2.",
        usage='%(prog)s ["<Notion URL or page_id>"] [--type {markdown,html,pdf}] [--timeout TIMEOUT] [--no-unzip] [--unzip-only ZIP] [--out-dir DIR]',
    )
    parser.add_argument("page", nargs="?", metavar="PAGE", help="Notion page URL or page ID")
    parser.add_argument("--type", choices=("markdown", "html", "pdf"), default="markdown")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--no-unzip", action="store_true")
    parser.add_argument("--unzip-only", type=Path, help="Safely extract an existing Notion export zip and exit")
    parser.add_argument("--out-dir", type=Path, help="Output directory for --unzip-only or export extraction")
    args = parser.parse_args()

    if args.unzip_only:
        zip_path = args.unzip_only if args.unzip_only.is_absolute() else ROOT / args.unzip_only
        out_dir, unzip_stats = unzip(zip_path, args.out_dir)
        print(json.dumps({
            "zip": display_path(zip_path),
            "bytes": zip_path.stat().st_size,
            "unzipped": display_path(out_dir),
            "unzip": unzip_stats,
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.page:
        parser.error("page is required unless --unzip-only is used")

    d = load_download_module()
    try:
        page_id = d.normalize_page_id(args.page)
    except ValueError as exc:
        parser.error(str(exc))

    token_v2 = d.normalize_token_v2(os.environ.get("NOTION_TOKEN_V2", ""))
    file_token = normalize_cookie_value(os.environ.get("NOTION_FILE_TOKEN", ""), "file_token")
    if not token_v2:
        raise SystemExit("NOTION_TOKEN_V2 is empty")
    if not file_token:
        raise SystemExit("NOTION_FILE_TOKEN is empty")

    space_id = infer_space_id(d)
    if not space_id:
        space_id = fetch_space_id_via_record_values(page_id, token_v2, file_token)
        if space_id:
            print(f"spaceId resolved via getRecordValues: {space_id}", file=sys.stderr)
    if not space_id:
        raise SystemExit(
            "Could not infer spaceId. Run "
            'python3 scripts/check_token_v2_block_access.py "<Notion URL or page_id>" '
            "and set NOTION_SPACE_ID to origins[].getRecordValues.space_id, then retry."
        )

    print(f"enqueue Notion export: page={page_id} space={space_id} type={args.type}", file=sys.stderr)
    task_id = enqueue_export(page_id, space_id, token_v2, file_token, args.type)
    print(f"export task id: {task_id}", file=sys.stderr)
    export_url = wait_for_export_url(task_id, space_id, token_v2, file_token, args.timeout)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = EXPORT_DIR / f"notion-export-{page_id[:12]}-{args.type}-{timestamp}.zip"
    print(f"downloading export zip to {zip_path.relative_to(ROOT)}", file=sys.stderr)
    download_url(export_url, zip_path, token_v2, file_token, space_id)

    result = {
        "zip": zip_path.relative_to(ROOT).as_posix(),
        "bytes": zip_path.stat().st_size,
    }
    if not args.no_unzip:
        out_dir, unzip_stats = unzip(zip_path, args.out_dir)
        result["unzipped"] = display_path(out_dir)
        result["unzip"] = unzip_stats

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
