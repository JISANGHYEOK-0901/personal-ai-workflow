#!/usr/bin/env python3
import argparse
import ast
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Dict, List, Match, Optional, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".notion-cache"
ASSET_MANIFEST_PATH = ROOT / ".notion-assets.json"

PAGE_TAG_RE = re.compile(r'<page url="([^"]+)"[^>]*>(.*?)</page>', re.DOTALL)
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\((file://.*?%7d)\)', re.I)
FILE_RE = re.compile(r'<file src="(file://[^"]+)"></file>')
BARE_PAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
BARE_UUID_PAGE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
PAGE_ID_IN_TEXT_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", re.I)
UUID_PAGE_ID_IN_TEXT_RE = re.compile(
    r"(?<![0-9a-f])([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])",
    re.I,
)
TITLE_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*", re.DOTALL)


def normalize_page_id(value: str) -> str:
    value = value.strip()
    if BARE_PAGE_ID_RE.fullmatch(value):
        return value.lower()
    if BARE_UUID_PAGE_ID_RE.fullmatch(value):
        return value.replace("-", "").lower()

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        locator = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))
        match = PAGE_ID_IN_TEXT_RE.search(locator)
        if match:
            return match.group(1).lower()
        match = UUID_PAGE_ID_IN_TEXT_RE.search(locator)
        if match:
            return match.group(1).replace("-", "").lower()

    raise ValueError(
        "expected a valid Notion URL containing a page ID, "
        "a 32-character page ID, or a hyphenated UUID page ID"
    )


def maybe_page_id(value: str) -> Optional[str]:
    try:
        return normalize_page_id(value)
    except ValueError:
        match = PAGE_ID_IN_TEXT_RE.search(value)
        if match:
            return match.group(1).lower()
        match = UUID_PAGE_ID_IN_TEXT_RE.search(value)
        if match:
            return match.group(1).replace("-", "").lower()
    return None


def run_ntn_pages_get(page_id: str) -> str:
    cache_path = CACHE_DIR / f"{page_id}.md"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    proc = subprocess.run(
        ["ntn", "pages", "get", page_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ntn pages get failed for {page_id}:\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(proc.stdout, encoding="utf-8")
    return proc.stdout


def extract_title(markdown: str, fallback: str) -> str:
    match = TITLE_RE.match(markdown)
    if not match:
        return fallback
    for line in match.group("body").splitlines():
        if not line.startswith("title:"):
            continue
        value = line.split(":", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.replace("\\'", "'").replace('\\"', '"') or fallback
    return fallback


def slugify(value: str, fallback: str) -> str:
    value = html.unescape(value).strip().lower()
    chars = []
    previous_dash = False
    for char in value:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif char in {".", "_", "-"}:
            chars.append(char)
            previous_dash = char == "-"
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-._")
    return slug or fallback


def unique_path(base_dir: Path, slug: str, used: Set[Path]) -> Path:
    candidate = base_dir / f"{slug}.md"
    index = 2
    while candidate in used:
        candidate = base_dir / f"{slug}-{index}.md"
        index += 1
    used.add(candidate)
    return candidate


def discover_pages(root_id: str) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    queue = deque([root_id])
    order: list[str] = []
    markdown_by_id: dict[str, str] = {}
    title_by_id: dict[str, str] = {}
    seen = {root_id}

    while queue:
        page_id = queue.popleft()
        print(f"Fetching {page_id} ...", file=sys.stderr)
        markdown = run_ntn_pages_get(page_id)
        markdown_by_id[page_id] = markdown
        title_by_id[page_id] = extract_title(markdown, page_id)
        order.append(page_id)

        for url, _body in PAGE_TAG_RE.findall(markdown):
            linked_id = maybe_page_id(url)
            if not linked_id:
                continue
            if linked_id in seen:
                continue
            seen.add(linked_id)
            queue.append(linked_id)

    return order, markdown_by_id, title_by_id


def assign_paths(order: List[str], title_by_id: Dict[str, str], root_id: str) -> Dict[str, Path]:
    pages_dir = ROOT / "pages"
    used: set[Path] = set()
    paths: dict[str, Path] = {}

    root_slug = slugify(title_by_id[root_id], root_id)
    paths[root_id] = unique_path(ROOT, root_slug, used)

    for page_id in order:
        if page_id == root_id:
            continue
        slug = slugify(title_by_id[page_id], page_id)
        paths[page_id] = unique_path(pages_dir, slug, used)
    return paths


def page_label(markup: str, fallback: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", markup, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\\*", "*").replace("*", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def replace_page_links(
    markdown: str,
    from_path: Path,
    paths: Dict[str, Path],
    title_by_id: Dict[str, str],
    link_log: List[Tuple[str, str, str]],
) -> Tuple[str, int]:
    count = 0

    def repl(match: Match[str]) -> str:
        nonlocal count
        url = match.group(1)
        body = match.group(2)
        linked_id = maybe_page_id(url)
        if not linked_id:
            label = page_label(body, url)
            return f"[{label}]({url})" if url and url != "..." else label
        if linked_id not in paths:
            return match.group(0)
        label = page_label(body, title_by_id.get(linked_id, linked_id))
        rel = os.path.relpath(paths[linked_id], start=from_path.parent)
        rel = rel.replace(os.sep, "/")
        count += 1
        link_log.append((from_path.as_posix(), label, rel))
        return f"[{label}]({rel})"

    return PAGE_TAG_RE.sub(repl, markdown), count


def sanitize_filename(value: str, fallback: str) -> str:
    value = urllib.parse.unquote(value).strip()
    if not value:
        value = fallback
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or fallback


def unique_asset_path(asset_dir: Path, filename: str, used: Set[Path]) -> Path:
    candidate = asset_dir / filename
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while candidate in used or candidate.exists():
        candidate = asset_dir / f"{stem}-{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def load_asset_manifest() -> Dict[str, Path]:
    if not ASSET_MANIFEST_PATH.exists():
        return {}
    try:
        data = json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}

    root_resolved = ROOT.resolve()
    manifest: dict[str, Path] = {}
    for source, rel_path in data.items():
        if not isinstance(source, str) or not isinstance(rel_path, str):
            continue
        path = (ROOT / rel_path).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            continue
        if path.exists() and path.stat().st_size > 0:
            manifest[source] = path
    return manifest


def write_asset_manifest(source_to_path: Dict[str, Path]) -> None:
    manifest = {}
    for source, path in sorted(source_to_path.items()):
        if not path.exists() or path.stat().st_size == 0:
            continue
        manifest[source] = path.relative_to(ROOT).as_posix()
    ASSET_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_token_value(raw: str) -> Optional[str]:
    raw = raw.strip()
    if not raw:
        return None

    if raw.startswith(("b'", 'b"')):
        try:
            value = ast.literal_eval(raw)
            if isinstance(value, bytes):
                raw = value.decode("utf-8")
        except (SyntaxError, ValueError, UnicodeDecodeError):
            pass

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    stack = [parsed]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in ("accessToken", "access_token", "token"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    return value
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


def get_keychain_token() -> str:
    if os.environ.get("NOTION_API_TOKEN"):
        return os.environ["NOTION_API_TOKEN"]

    commands = [
        ["security", "find-generic-password", "-s", "notion-cli", "-w"],
        ["security", "find-generic-password", "-s", "so.notion.ntn", "-w"],
    ]
    for command in commands:
        proc = subprocess.run(command, text=True, capture_output=True)
        token = extract_token_value(proc.stdout)
        if proc.returncode == 0 and token:
            return token
    raise RuntimeError(
        "Could not read a Notion token from NOTION_API_TOKEN or macOS Keychain."
    )


def normalize_token_v2(value: str) -> str:
    value = value.strip().strip("'\"")
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()

    for part in value.split(";"):
        part = part.strip()
        if part.startswith("token_v2="):
            return part.split("=", 1)[1].strip().strip("'\"")

    if value.startswith("token_v2="):
        return value.split("=", 1)[1].strip().strip("'\"")
    return value


def get_session_token() -> Optional[str]:
    token = normalize_token_v2(os.environ.get("NOTION_TOKEN_V2", ""))
    return token or None


def extract_signed_url(body: dict) -> Optional[str]:
    values = body.get("signedUrls") or body.get("urls") or []
    if not values:
        return None
    signed = values[0]
    if isinstance(signed, dict):
        signed = signed.get("url") or signed.get("signedUrl")
    if not signed or signed == "b''":
        return None
    return signed


def signed_file_url(ref: dict, api_token: Optional[str], session_token: Optional[str]) -> Optional[str]:
    payload = {
        "urls": [
            {
                "url": ref["source"],
                "permissionRecord": ref["permissionRecord"],
            }
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    if session_token:
        headers["Cookie"] = f"token_v2={session_token}"
    elif api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    req = urllib.request.Request(
        "https://www.notion.so/api/v3/getSignedFileUrls",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = json.load(response)
    return extract_signed_url(body)


def requote_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    path = urllib.parse.quote(parts.path, safe="/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def is_notion_host(url: str) -> bool:
    # Notion-session auth (Bearer / token_v2 cookie) must attach for Notion-hosted
    # assets on notion.so AND notion.com (e.g. file.notion.com), but NOT for S3
    # pre-signed URLs (amazonaws.com), which need no headers. A bare "notion.so/"
    # substring check misses file.notion.com and 403s / returns HTML.
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return (
        host == "notion.so"
        or host.endswith(".notion.so")
        or host == "notion.com"
        or host.endswith(".notion.com")
    )


def download_file(
    url: str,
    path: Path,
    api_token: Optional[str] = None,
    session_token: Optional[str] = None,
) -> None:
    headers = {"User-Agent": "notion-local-backup/1.0"}
    if is_notion_host(url):
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        if session_token:
            headers["Cookie"] = f"token_v2={session_token}"
    req = urllib.request.Request(
        requote_url(url),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        content_type = response.headers.get("content-type", "")
        body = response.read()
    if is_notion_host(url) and content_type.startswith("text/html"):
        raise RuntimeError("Notion returned HTML instead of a file")
    path.write_bytes(body)


def parse_image_ref(file_url: str) -> dict:
    encoded = file_url.removeprefix("file://")
    return json.loads(urllib.parse.unquote(encoded))


def resolve_and_download_ref(
    ref: dict,
    api_token: Optional[str],
    session_token: Optional[str],
    local_path: Path,
    kind: str,
) -> bool:
    source = ref.get("source")
    if not source:
        return False
    candidates: list[str] = []
    try:
        signed = signed_file_url(ref, api_token, session_token)
    except Exception as exc:
        print(f"warning: failed to sign {source}: {exc}", file=sys.stderr)
        signed = None
    if signed:
        candidates.append(signed)
    elif source.startswith(("http://", "https://")):
        candidates.append(source)

    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            download_file(
                url,
                local_path,
                api_token=api_token,
                session_token=session_token,
            )
            return True
        except Exception as exc:
            print(f"warning: failed to download {source}: {exc}", file=sys.stderr)
    return False


def localize_attachments(
    markdown: str,
    from_path: Path,
    source_to_path: Dict[str, Path],
    used_assets: Set[Path],
) -> Tuple[str, int, int, List[str]]:
    image_matches = list(IMAGE_RE.finditer(markdown))
    file_matches = list(FILE_RE.finditer(markdown))
    if not image_matches and not file_matches:
        return markdown, 0, 0, []

    session_token = get_session_token()
    try:
        api_token = get_keychain_token()
    except RuntimeError:
        if not session_token:
            raise
        api_token = None

    asset_dir = ROOT / "assets" if from_path.parent == ROOT else from_path.parent / "assets" / from_path.stem
    asset_dir.mkdir(parents=True, exist_ok=True)
    image_count = 0
    file_count = 0
    unresolved: list[str] = []

    def local_path_for_ref(ref: dict) -> Path:
        source = ref.get("source", "")
        raw_name = source.split(":", 2)[-1] if ":" in source else source
        raw_name = Path(raw_name).name
        if source.startswith(("http://", "https://")):
            raw_name = urllib.parse.urlsplit(source).path.rsplit("/", 1)[-1]
        filename = sanitize_filename(raw_name, f"attachment-{len(source_to_path) + 1:02d}")
        candidate = asset_dir / filename
        if candidate not in used_assets:
            used_assets.add(candidate)
            return candidate
        return unique_asset_path(asset_dir, filename, used_assets)

    def localize_ref(file_url: str, kind: str) -> Optional[Path]:
        try:
            ref = parse_image_ref(file_url)
        except json.JSONDecodeError:
            unresolved.append(f"{from_path.relative_to(ROOT)} -> malformed file URL")
            return None
        source = ref.get("source")
        if not source:
            return None

        if source in source_to_path:
            existing_path = source_to_path[source]
            if existing_path.exists() and existing_path.stat().st_size > 0:
                return existing_path

        local_path = local_path_for_ref(ref)
        if local_path.exists() and local_path.stat().st_size > 0:
            source_to_path[source] = local_path
            return local_path

        if not resolve_and_download_ref(ref, api_token, session_token, local_path, kind):
            unresolved.append(f"{from_path.relative_to(ROOT)} -> {source}")
            return None

        source_to_path[source] = local_path
        return local_path

    def image_repl(match: Match[str]) -> str:
        nonlocal image_count
        alt = match.group(1)
        file_url = match.group(2)
        local_path = localize_ref(file_url, "image")
        if not local_path:
            return match.group(0)
        image_count += 1

        rel = os.path.relpath(local_path, start=from_path.parent).replace(os.sep, "/")
        return f"![{alt}]({rel})"

    def file_repl(match: Match[str]) -> str:
        nonlocal file_count
        file_url = match.group(1)
        ref = parse_image_ref(file_url)
        local_path = localize_ref(file_url, "file")
        if not local_path:
            return match.group(0)
        file_count += 1
        rel = os.path.relpath(local_path, start=from_path.parent).replace(os.sep, "/")
        label = sanitize_filename(ref.get("source", "").rsplit(":", 1)[-1], local_path.name)
        return f"[{label}]({rel})"

    markdown = IMAGE_RE.sub(image_repl, markdown)
    markdown = FILE_RE.sub(file_repl, markdown)
    return markdown, image_count, file_count, unresolved


def write_pages(
    order: List[str],
    markdown_by_id: Dict[str, str],
    title_by_id: Dict[str, str],
    paths: Dict[str, Path],
) -> dict:
    source_to_path = load_asset_manifest()
    used_assets: set[Path] = set(source_to_path.values())
    link_log: list[tuple[str, str, str]] = []
    image_count = 0
    file_count = 0
    link_count = 0
    unresolved_assets: list[str] = []

    for page_id in order:
        path = paths[page_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        markdown = markdown_by_id[page_id]
        markdown, links = replace_page_links(markdown, path, paths, title_by_id, link_log)
        markdown, images, files, unresolved = localize_attachments(
            markdown, path, source_to_path, used_assets
        )
        path.write_text(markdown, encoding="utf-8")
        link_count += links
        image_count += images
        file_count += files
        unresolved_assets.extend(unresolved)

    write_asset_manifest(source_to_path)

    return {
        "pages": len(order),
        "images": image_count,
        "files": file_count,
        "links": link_count,
        "unresolved_assets": unresolved_assets,
        "asset_manifest_entries": len(source_to_path),
        "paths": {page_id: paths[page_id].relative_to(ROOT).as_posix() for page_id in order},
        "link_log": link_log,
    }


def verify(summary: dict) -> dict:
    markdown_files = [ROOT / path for path in summary["paths"].values()]
    file_url_left = 0
    page_tag_left = 0
    missing_images: list[str] = []

    for md_path in markdown_files:
        text = md_path.read_text(encoding="utf-8")
        file_url_left += text.count("file://")
        page_tag_left += len(PAGE_TAG_RE.findall(text))
        for _alt, url in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text):
            if "://" in url:
                continue
            asset_path = (md_path.parent / url).resolve()
            if not asset_path.exists():
                missing_images.append(f"{md_path.relative_to(ROOT)} -> {url}")

    return {
        "saved_markdown": len(markdown_files),
        "file_url_left": file_url_left,
        "page_tag_left": page_tag_left,
        "missing_images": missing_images,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recursively export a Notion page with assets.",
        usage='%(prog)s "<Notion URL or page_id>"',
    )
    parser.add_argument("page", metavar="PAGE", help="Root Notion page URL or page ID")
    args = parser.parse_args()

    try:
        root_id = normalize_page_id(args.page)
    except ValueError as exc:
        parser.error(str(exc))

    order, markdown_by_id, title_by_id = discover_pages(root_id)
    paths = assign_paths(order, title_by_id, root_id)
    summary = write_pages(order, markdown_by_id, title_by_id, paths)
    checks = verify(summary)
    summary["checks"] = checks

    report_path = ROOT / "backup-summary.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "pages": summary["pages"],
        "images": summary["images"],
        "files": summary["files"],
        "links": summary["links"],
        "unresolved_assets": len(summary["unresolved_assets"]),
        "asset_manifest_entries": summary["asset_manifest_entries"],
        "checks": checks,
        "report": report_path.relative_to(ROOT).as_posix(),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    if checks["file_url_left"] or checks["page_tag_left"] or checks["missing_images"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
