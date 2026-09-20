#!/usr/bin/env python3
"""Least-privilege Weknora chunk discovery, update, and verification client."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    def __init__(self, status: int, body: object):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def config() -> tuple[str, dict[str, str]]:
    base = os.environ.get("WEKNORA_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("WEKNORA_API_KEY", "")
    token = os.environ.get("WEKNORA_ACCESS_TOKEN", "")
    if not base:
        raise ValueError("WEKNORA_BASE_URL is required")
    if bool(api_key) == bool(token):
        raise ValueError("Set exactly one of WEKNORA_API_KEY or WEKNORA_ACCESS_TOKEN")
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {token}"
    # Accept either the server origin (http://host:8781) or an API URL
    # copied from the integration page (http://host:8781/api/v1).
    api_base = base if base.endswith("/api/v1") else base + "/api/v1"
    return api_base, headers


def request(method: str, path: str, *, params: dict[str, object] | None = None, body: object | None = None) -> object:
    base, headers = config()
    url = base + path
    if params:
        url += "?" + urlencode({key: value for key, value in params.items() if value is not None})
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        raise ApiError(exc.code, parsed) from exc
    except URLError as exc:
        raise RuntimeError(f"Connection failed: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def data_of(payload: object) -> object:
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def all_pages(path: str, *, params: dict[str, object] | None = None) -> list[dict]:
    query = dict(params or {})
    query.setdefault("page_size", 100)
    page = 1
    records: list[dict] = []
    while True:
        query["page"] = page
        payload = request("GET", path, params=query)
        items = data_of(payload)
        if not isinstance(items, list):
            raise RuntimeError("Expected a list response")
        records.extend(item for item in items if isinstance(item, dict))
        total = payload.get("total") if isinstance(payload, dict) else None
        if not items or (isinstance(total, int) and len(records) >= total) or len(items) < int(query["page_size"]):
            return records
        page += 1


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def require_nonempty(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def cmd_list_kbs(_: argparse.Namespace) -> object:
    return all_pages("/knowledge-bases")


def cmd_list_documents(args: argparse.Namespace) -> object:
    return all_pages(f"/knowledge-bases/{args.knowledge_base_id}/knowledge")


def cmd_find_document(args: argparse.Namespace) -> object:
    name = require_nonempty(args.name, "--name")
    matches = []
    for item in cmd_list_documents(args):
        if item.get("name") == name or item.get("title") == name:
            matches.append(item)
    return {"match_count": len(matches), "matches": matches}


def cmd_find_document_global(args: argparse.Namespace) -> object:
    """Find an exact document name across every KB visible to the API principal."""
    name = require_nonempty(args.name, "--name")
    matches: list[dict] = []
    inaccessible: list[dict] = []
    for knowledge_base in cmd_list_kbs(args):
        knowledge_base_id = knowledge_base.get("id")
        if not isinstance(knowledge_base_id, str) or not knowledge_base_id:
            continue
        try:
            documents = all_pages(f"/knowledge-bases/{knowledge_base_id}/knowledge")
        except ApiError as exc:
            inaccessible.append({
                "knowledge_base_id": knowledge_base_id,
                "status": exc.status,
            })
            continue
        for document in documents:
            if document.get("name") != name and document.get("title") != name:
                continue
            knowledge_id = document.get("id")
            if not isinstance(knowledge_id, str) or not knowledge_id:
                continue
            matches.append({
                "knowledge_base_id": knowledge_base_id,
                "knowledge_base_name": knowledge_base.get("name"),
                "knowledge_id": knowledge_id,
                "document_name": document.get("name") or document.get("title"),
            })
    return {
        "match_count": len(matches),
        "matches": matches,
        "inaccessible_knowledge_base_count": len(inaccessible),
        "inaccessible_knowledge_bases": inaccessible,
    }


def locate_text(document_name: str, text: str) -> dict:
    """Resolve the document and target chunk without accepting caller-provided IDs."""
    resolved = cmd_find_document_global(argparse.Namespace(name=document_name))
    documents = resolved["matches"]
    if len(documents) != 1:
        return {
            "document_match_count": len(documents),
            "document_matches": documents,
            "text_match_count": 0,
            "text_matches": [],
            "inaccessible_knowledge_bases": resolved["inaccessible_knowledge_bases"],
        }
    document = documents[0]
    chunks = all_pages(f"/chunks/{document['knowledge_id']}")
    matches = []
    for chunk in chunks:
        content = str(chunk.get("content", ""))
        if text in content:
            matches.append({
                "knowledge_id": document["knowledge_id"],
                "knowledge_base_id": document["knowledge_base_id"],
                "document_name": document["document_name"],
                "chunk_id": chunk.get("id"),
                "chunk_index": chunk.get("chunk_index"),
                "content_revision": chunk.get("content_revision"),
                "content": content,
            })
    return {
        "document_match_count": 1,
        "document_matches": documents,
        "text_match_count": len(matches),
        "text_matches": matches,
        "inaccessible_knowledge_bases": resolved["inaccessible_knowledge_bases"],
    }


def require_unique_text_match(document_name: str, old_text: str) -> dict:
    result = locate_text(document_name, old_text)
    if result["document_match_count"] != 1:
        raise ValueError("Document name did not resolve to exactly one API-accessible document")
    if result["text_match_count"] != 1:
        raise ValueError("Old text did not resolve to exactly one chunk")
    match = result["text_matches"][0]
    if not isinstance(match.get("chunk_id"), str) or not match["chunk_id"]:
        raise RuntimeError("Resolved chunk has no ID")
    if match["content"].count(old_text) != 1:
        raise ValueError("Old text must occur exactly once within the selected chunk")
    return match


def cmd_preview_replace(args: argparse.Namespace) -> object:
    match = require_unique_text_match(args.document_name, args.old_text)
    content = match["content"]
    replacement = content.replace(args.old_text, args.new_text, 1)
    return {
        "document_name": match["document_name"],
        "knowledge_id": match["knowledge_id"],
        "chunk_id": match["chunk_id"],
        "chunk_index": match["chunk_index"],
        "content_revision": match["content_revision"],
        "old_text": args.old_text,
        "new_text": args.new_text,
        "before_content": content,
        "after_content": replacement,
    }


def cmd_commit_replace(args: argparse.Namespace) -> object:
    match = require_unique_text_match(args.document_name, args.old_text)
    current_revision = match.get("content_revision")
    if current_revision is None:
        raise RuntimeError("Chunk response has no content_revision; refuse unsafe update")
    if current_revision != args.expected_revision:
        raise ValueError("Chunk revision changed; run preview-replace again before committing")
    replacement = match["content"].replace(args.old_text, args.new_text, 1)
    return request(
        "PUT",
        f"/chunks/{match['knowledge_id']}/{match['chunk_id']}",
        body={"content": replacement, "expected_revision": args.expected_revision},
    )


def cmd_verify_replace(args: argparse.Namespace) -> object:
    result = locate_text(args.document_name, args.new_text)
    return {
        "document_match_count": result["document_match_count"],
        "new_text_match_count": result["text_match_count"],
        "matches": result["text_matches"],
        "inaccessible_knowledge_bases": result["inaccessible_knowledge_bases"],
    }


def cmd_list_chunks(args: argparse.Namespace) -> object:
    return all_pages(f"/chunks/{args.knowledge_id}", params={"chunk_type": args.chunk_type})


def cmd_get_chunk(args: argparse.Namespace) -> object:
    return request("GET", f"/chunks/by-id/{args.chunk_id}")


def cmd_find_text(args: argparse.Namespace) -> object:
    needle = require_nonempty(args.text, "--text")
    matches = [item for item in cmd_list_chunks(args) if needle in str(item.get("content", ""))]
    return {"match_count": len(matches), "matches": matches}


def cmd_update_chunk(args: argparse.Namespace) -> object:
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    require_nonempty(content, "--content or --content-file")
    return request(
        "PUT",
        f"/chunks/{args.knowledge_id}/{args.chunk_id}",
        body={"content": content, "expected_revision": args.expected_revision},
    )


def cmd_verify_chunk(args: argparse.Namespace) -> object:
    payload = cmd_get_chunk(args)
    chunk = data_of(payload)
    content = chunk.get("content", "") if isinstance(chunk, dict) else ""
    return {
        "contains_expected_text": args.contains in content,
        "content_revision": chunk.get("content_revision") if isinstance(chunk, dict) else None,
        "index_status": chunk.get("index_status") if isinstance(chunk, dict) else None,
        "chunk": chunk,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview-replace")
    preview.add_argument("--document-name", required=True)
    preview.add_argument("--old-text", required=True)
    preview.add_argument("--new-text", required=True)
    preview.set_defaults(handler=cmd_preview_replace)

    commit = sub.add_parser("commit-replace")
    commit.add_argument("--document-name", required=True)
    commit.add_argument("--old-text", required=True)
    commit.add_argument("--new-text", required=True)
    commit.add_argument("--expected-revision", type=int, required=True)
    commit.set_defaults(handler=cmd_commit_replace)

    verify_replace = sub.add_parser("verify-replace")
    verify_replace.add_argument("--document-name", required=True)
    verify_replace.add_argument("--new-text", required=True)
    verify_replace.set_defaults(handler=cmd_verify_replace)

    return root


def main() -> int:
    args = parser().parse_args()
    try:
        emit(args.handler(args))
        return 0
    except ApiError as exc:
        emit({"success": False, "status": exc.status, "error": exc.body})
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        emit({"success": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
