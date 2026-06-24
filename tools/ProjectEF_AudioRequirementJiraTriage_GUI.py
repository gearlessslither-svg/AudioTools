#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Iterable
from xml.etree import ElementTree

try:
    import openpyxl
except Exception:  # pragma: no cover - optional dependency
    openpyxl = None

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
except Exception:  # pragma: no cover - optional dependency
    pdfminer_extract_text = None

try:
    import win32crypt
except Exception:  # pragma: no cover - Windows-only optional dependency
    win32crypt = None

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - optional dependency
    AESGCM = None


ROOT = Path(r"G:\AI\Material\Wwise")
APP_DIR = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "\u62A5\u544A"
INDEX_PATH = APP_DIR / "audio_requirement_jira_index.json"
QA_INDEX_PATH = APP_DIR / "audio_requirement_qa_index.json"
CONFIG_PATH = APP_DIR / "audio_requirement_jira_triage_config.json"
JIRA_CACHE_PATH = APP_DIR / "audio_requirement_jira_issue_cache.json"
SNAPSHOT_DIR = APP_DIR / "audio_requirement_snapshots"
LATEST_DIFF_PATH = APP_DIR / "audio_requirement_design_diff_latest.json"
DEDICATED_JIRA_PROFILE_DIR = APP_DIR / "jira_browser_profile"
JIRA_CDP_PORT = 9233

DEFAULT_DESIGN_ROOT = Path(r"D:\EF New\Design")
DEFAULT_JIRA_URL = "http://ef.jira.blackjack-local.com:8080"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5:7b-instruct"
INDEX_VERSION = 1
QA_INDEX_VERSION = 1
JIRA_CACHE_VERSION = 1
JIRA_SEARCH_FIELDS = "summary,description,status,assignee,reporter,creator,updated,fixVersions,versions,components,labels,issuetype,priority,project,issuelinks,subtasks,parent,attachment"
MATCH_STATUS_MATCHED = "Matched"
MATCH_STATUS_NOT_MATCHED = "NotMatched"
MATCH_STATUS_NEEDS_REMATCH = "NeedsRematch"
NO_EVIDENCE_LABEL = "NoEvidence"
UNMATCHED_DESIGN_LABEL = MATCH_STATUS_NOT_MATCHED
MATCH_RESULT_FIELDS = (
    "evidence",
    "audio_required",
    "ready_state",
    "confidence",
    "reason",
    "can_start",
    "system",
    "design_area",
    "design_doc",
    "sound_type",
    "qa_cases",
    "qa_summary",
    "qa_path",
    "qa_open_target",
    "qa_link_status",
    "match_status",
    "matched_at",
)
JIRA_MATCH_INPUT_FIELDS = (
    "summary",
    "description",
    "components",
    "labels",
    "issue_links",
    "qa_doc_refs",
    "qa_design_issues",
)

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".html", ".htm"}
TABLE_EXTENSIONS = {".xlsx"}
DOC_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | TABLE_EXTENSIONS | DOC_EXTENSIONS | PDF_EXTENSIONS
QA_TEXT_EXTENSIONS = {".md", ".txt"}
QA_SOURCE_EXTENSIONS = QA_TEXT_EXTENSIONS | {".xmind"}
MAX_DESIGN_PARSE_BYTES = 50 * 1024 * 1024
JIRA_QA_FIELD_HINTS = {
    "qa",
    "smoke",
    "test",
    "case",
    "checklist",
    "\u5192\u70df",
    "\u6d4b\u8bd5",
    "\u7528\u4f8b",
    "\u9a8c\u6536",
    "\u6d4b\u8bd5\u6587\u6863",
    "\u7528\u4f8b\u6587\u6863",
}
QA_DESIGN_ISSUE_HINTS = {
    "qa",
    "test case",
    "testcase",
    "checklist",
    "acceptance",
    "\u6d4b\u8bd5\u7528\u4f8b\u8bbe\u8ba1",
    "\u6d4b\u8bd5\u7528\u4f8b",
    "\u7528\u4f8b\u8bbe\u8ba1",
    "\u7528\u4f8b",
    "\u9a8c\u6536",
}
QA_PATH_EXTENSIONS = (".md", ".txt", ".xlsx", ".csv", ".html", ".htm", ".xmind")
SKIP_DIR_TOKENS = {
    ".git",
    ".svn",
    ".cursor",
    ".qoder",
    ".vscode",
    "__pycache__",
    "node_modules",
    "backup",
    "backups",
    "bak",
    "\u5907\u4efd\u6587\u4ef6",
    "GeneriteFile".lower(),
    "StringTableKeyCache".lower(),
    "MD5".lower(),
}

AUDIO_DIRECT = {
    "audio",
    "sound",
    "sfx",
    "bgm",
    "music",
    "voice",
    "wwise",
    "\u97f3\u9891",
    "\u58f0\u97f3",
    "\u97f3\u6548",
    "\u58f0\u6548",
    "\u97f3\u4e50",
    "\u914d\u97f3",
    "\u8bed\u97f3",
    "\u73af\u5883\u97f3",
    "\u97f3\u8272",
    "\u97f3\u91cf",
}
GAMEPLAY_AUDIO_HINTS = {
    "\u52a8\u753b",
    "\u8868\u73b0",
    "\u7279\u6548",
    "vfx",
    "\u70b9\u51fb",
    "\u6309\u94ae",
    "ui",
    "\u63d0\u793a",
    "\u8b66\u544a",
    "\u6210\u529f",
    "\u5931\u8d25",
    "\u5956\u52b1",
    "\u7ed3\u7b97",
    "\u89e6\u53d1",
    "\u4e8b\u4ef6",
    "\u53cd\u9988",
    "\u9c7c",
    "\u54ac\u94a9",
    "\u629b\u6295",
    "\u6536\u7ebf",
    "\u9c7c\u7aff",
    "\u6c34\u82b1",
    "\u6c34\u9762",
    "\u5929\u6c14",
    "\u96e8",
    "\u98ce",
    "\u9e1f",
    "\u751f\u7269",
    "\u8239",
    "\u9053\u5177",
    "\u88c5\u5907",
}
READY_HINTS = {
    "\u89e6\u53d1",
    "\u72b6\u6001",
    "\u65f6\u673a",
    "\u64ad\u653e",
    "\u8fdb\u5165",
    "\u79bb\u5f00",
    "\u5f00\u59cb",
    "\u7ed3\u675f",
    "\u6210\u529f",
    "\u5931\u8d25",
    "\u51fa\u73b0",
    "\u70b9\u51fb",
}
BLOCKER_HINTS = {
    "todo",
    "tbd",
    "\u5f85\u5b9a",
    "\u6682\u5b9a",
    "\u672a\u5b9a",
    "\u9700\u786e\u8ba4",
    "\u7f3a",
    "\u5360\u4f4d",
}
TOKEN_STOP = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "assets",
    "gameproject",
    "design",
    "jira",
    "projectef",
}
GENERIC_QUERY_TERMS = {
    "\u97f3\u6548",
    "\u58f0\u97f3",
    "\u97f3\u9891",
    "\u9700\u8981",
    "\u5224\u65ad",
    "\u662f\u5426",
    "\u7b56\u5212",
    "\u6587\u6863",
    "\u6587\u6848",
    "\u529f\u80fd",
    "\u9700\u6c42",
    "\u8868\u73b0",
    "\u53cd\u9988",
    "\u52a8\u753b",
    "\u7279\u6548",
    "\u89e6\u53d1",
    "\u914d\u7f6e",
    "\u73a9\u6cd5",
    "\u7cfb\u7edf",
}
SPECIFIC_TERM_LEXICON = {
    "\u9e1f",
    "\u9e1f\u7c7b",
    "\u7fc5\u8180",
    "\u73af\u5883\u751f\u7269",
    "\u751f\u7269",
    "\u9c7c",
    "\u54ac\u94a9",
    "\u629b\u6295",
    "\u6536\u7ebf",
    "\u9c7c\u7aff",
    "\u6d6e\u6f02",
    "\u7a9d\u6599",
    "\u6309\u94ae",
    "\u70b9\u51fb",
    "\u5546\u5e97",
    "\u5956\u52b1",
    "\u6210\u5c31",
    "\u4efb\u52a1",
    "\u5929\u6c14",
    "\u98ce",
    "\u96e8",
    "\u8239",
    "\u89d2\u8272",
    "\u6280\u80fd",
    "\u6c34\u82b1",
}

BG = "#0f1722"
PANEL = "#151f2d"
PANEL_2 = "#1b2636"
CARD = "#202c3d"
INK = "#edf4ff"
MUTED = "#9fb0c6"
LINE = "#334258"
WARN = "#ffcc66"


@dataclass
class DocumentChunk:
    doc_id: str
    path: str
    title: str
    locator: str
    text: str
    tokens: set[str]
    audio_score: float
    sabc: str
    ready_state: str
    sound_type: str
    reason: str


def now_stamp() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def normalize_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]


def strip_html(text: str) -> str:
    if not text:
        return ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text("\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str) -> set[str]:
    lowered = normalize_path(text).lower()
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9_]+", lowered):
        for item in raw.split("_"):
            if len(item) >= 2 and item not in TOKEN_STOP:
                tokens.add(item)
    for raw in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        tokens.add(raw)
        for i in range(0, max(0, len(raw) - 1)):
            tokens.add(raw[i : i + 2])
    return tokens


def specific_query_terms(text: str) -> set[str]:
    lowered = normalize_path(text).lower()
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9_]+", lowered):
        for item in raw.split("_"):
            if len(item) >= 2 and item not in TOKEN_STOP:
                tokens.add(item)
    tokens.update(term for term in SPECIFIC_TERM_LEXICON if term.lower() in lowered)
    generic = set(GENERIC_QUERY_TERMS)
    generic.update(AUDIO_DIRECT)
    generic.update({"\u98de\u884c", "ui", "audio", "sound", "sfx"})
    result = {token for token in tokens if token not in generic and len(token) >= 2}
    if "\u9e1f" in lowered:
        result.add("\u9e1f")
    return result


def text_has_any(text: str, words: set[str]) -> list[str]:
    lowered = text.lower()
    return [word for word in words if word and word.lower() in lowered]


def classify_audio_need(text: str, path: str) -> tuple[float, str, str, str, str]:
    hay = f"{path}\n{text}"
    direct = text_has_any(hay, AUDIO_DIRECT)
    hints = text_has_any(hay, GAMEPLAY_AUDIO_HINTS)
    ready = text_has_any(hay, READY_HINTS)
    blockers = text_has_any(hay, BLOCKER_HINTS)

    score = min(1.0, 0.18 * len(direct) + 0.06 * len(hints))
    if direct:
        score = max(score, 0.62)
    elif len(hints) >= 2:
        score = max(score, 0.34)

    if any(word in hay.lower() for word in ["bgm", "music", "\u97f3\u4e50"]):
        sound_type = "Music"
    elif any(word in hay.lower() for word in ["ui", "\u70b9\u51fb", "\u6309\u94ae", "\u754c\u9762"]):
        sound_type = "UI"
    elif any(word in hay.lower() for word in ["\u5929\u6c14", "\u98ce", "\u96e8", "\u9e1f", "\u751f\u7269", "\u73af\u5883"]):
        sound_type = "Environment"
    elif any(word in hay.lower() for word in ["\u8bed\u97f3", "\u914d\u97f3", "voice"]):
        sound_type = "VO"
    elif any(word in hay.lower() for word in ["\u52a8\u753b", "\u7279\u6548", "vfx"]):
        sound_type = "VFX/Foley"
    else:
        sound_type = "Gameplay"

    if any(word in hay.lower() for word in ["\u54ac\u94a9", "\u629b\u6295", "\u6536\u7ebf", "\u8b66\u544a", "\u6210\u529f", "\u5931\u8d25"]):
        sabc = "S"
    elif direct or any(word in hay.lower() for word in ["ui", "\u7279\u6548", "\u52a8\u753b", "\u5956\u52b1"]):
        sabc = "A"
    elif sound_type in {"Environment", "VFX/Foley"}:
        sabc = "B"
    else:
        sabc = "C"

    if blockers:
        ready_state = "Risky"
    elif direct and ready:
        ready_state = "Ready"
    elif direct or hints:
        ready_state = "DesignOnly"
    else:
        ready_state = "Unknown"

    reason_bits = []
    if direct:
        reason_bits.append("direct audio terms: " + ", ".join(direct[:5]))
    if hints:
        reason_bits.append("gameplay/audio-adjacent terms: " + ", ".join(hints[:5]))
    if blockers:
        reason_bits.append("blocker terms: " + ", ".join(blockers[:3]))
    reason = "; ".join(reason_bits) or "no explicit audio evidence"
    return round(score, 3), sabc, ready_state, sound_type, reason


def chunk_plain_text(path: Path, root: Path, text: str, max_chars: int = 1400) -> list[dict[str, str]]:
    text = clean_text(text)
    if not text:
        return []
    lines = text.splitlines()
    chunks: list[dict[str, str]] = []
    current: list[str] = []
    section = path.stem
    start_line = 1
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped[:160].lstrip("#").strip() or section
        if not current:
            start_line = idx
        current.append(line)
        current_text = "\n".join(current).strip()
        if len(current_text) >= max_chars or (stripped.startswith("#") and len(current) > 1):
            if current_text:
                chunks.append({"title": section, "locator": f"line {start_line}", "text": current_text})
            current = [line] if stripped.startswith("#") else []
            start_line = idx
    if current:
        chunks.append({"title": section, "locator": f"line {start_line}", "text": "\n".join(current).strip()})
    return chunks


def read_text_file(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def chunks_from_xlsx(path: Path, _root: Path) -> list[dict[str, str]]:
    if openpyxl is None:
        return []
    chunks: list[dict[str, str]] = []
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return []
    try:
        for sheet in workbook.worksheets:
            header: list[str] = []
            buffer: list[str] = []
            start_row = 1
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), 1):
                values = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                if not values:
                    continue
                if not header:
                    header = values[:12]
                    continue
                pairs = []
                for i, value in enumerate(values[:12]):
                    key = header[i] if i < len(header) else f"col{i + 1}"
                    pairs.append(f"{key}: {value}")
                if not buffer:
                    start_row = row_index
                buffer.append(" | ".join(pairs))
                if len(buffer) >= 18:
                    chunks.append({
                        "title": sheet.title,
                        "locator": f"{sheet.title}!row {start_row}-{row_index}",
                        "text": "\n".join(buffer),
                    })
                    buffer = []
            if buffer:
                chunks.append({
                    "title": sheet.title,
                    "locator": f"{sheet.title}!row {start_row}-{start_row + len(buffer) - 1}",
                    "text": "\n".join(buffer),
                })
    finally:
        try:
            workbook.close()
        except Exception:
            pass
    return chunks


def chunks_from_docx(path: Path, root: Path) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except Exception:
        return []
    try:
        tree = ElementTree.fromstring(xml_bytes)
    except Exception:
        return []
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in tree.findall(".//w:p", ns):
        texts = [node.text or "" for node in para.findall(".//w:t", ns)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return chunk_plain_text(path, root, "\n".join(paragraphs))


def chunks_from_pdf(path: Path, root: Path) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            for page_index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                for chunk in chunk_plain_text(path, root, text):
                    chunk["locator"] = f"page {page_index} {chunk.get('locator', '')}".strip()
                    chunks.append(chunk)
            if chunks:
                return chunks
        except Exception:
            chunks = []

    if pdfminer_extract_text is not None:
        try:
            text = pdfminer_extract_text(str(path)) or ""
        except Exception:
            return []
        return chunk_plain_text(path, root, text)

    return []


def chunks_from_file(path: Path, root: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        text = read_text_file(path)
        if suffix in {".html", ".htm"}:
            text = strip_html(text)
        return chunk_plain_text(path, root, text)
    if suffix == ".xlsx":
        return chunks_from_xlsx(path, root)
    if suffix == ".docx":
        return chunks_from_docx(path, root)
    if suffix == ".pdf":
        return chunks_from_pdf(path, root)
    return []


def should_skip(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return (
        any(token.lower() in lowered_parts for token in SKIP_DIR_TOKENS)
        or ".bak" in name
        or "backup" in name
        or "\u5907\u4efd" in name
        or "sync-conflict" in name
    )


def build_design_index(
    root: Path,
    progress=None,
    limit: int = 0,
    previous_index: dict[str, Any] | None = None,
    max_parse_bytes: int = MAX_DESIGN_PARSE_BYTES,
    should_cancel=None,
) -> dict[str, Any]:
    root = root.resolve()
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not should_skip(path)
    ]
    files.sort(key=lambda item: normalize_path(item).lower())
    if limit:
        files = files[:limit]

    previous_index = previous_index or {}
    previous_docs = {
        str(doc.get("path") or ""): doc
        for doc in previous_index.get("documents", []) or []
        if isinstance(doc, dict) and doc.get("path")
    }
    previous_chunks_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in previous_index.get("chunks", []) or []:
        if isinstance(chunk, dict) and chunk.get("doc_path"):
            previous_chunks_by_path[str(chunk.get("doc_path"))].append(chunk)
    previous_requirements_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for req in previous_index.get("requirements", []) or []:
        if isinstance(req, dict) and req.get("doc_path"):
            previous_requirements_by_path[str(req.get("doc_path"))].append(req)

    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    reused_docs = 0
    parsed_docs = 0
    skipped_large_files = 0

    for file_index, path in enumerate(files, 1):
        if should_cancel and should_cancel():
            raise RuntimeError("Scan canceled.")
        if progress:
            progress(f"Scanning {file_index}/{len(files)}: {path.name}")
        try:
            stat = path.stat()
            rel = normalize_path(path.relative_to(root))
            mtime = dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            previous_doc = previous_docs.get(rel)
            if (
                previous_doc
                and str(previous_doc.get("mtime") or "") == mtime
                and int(previous_doc.get("size") or -1) == stat.st_size
            ):
                documents.append(dict(previous_doc))
                chunks.extend(dict(item) for item in previous_chunks_by_path.get(rel, []))
                requirements.extend(dict(item) for item in previous_requirements_by_path.get(rel, []))
                reused_docs += 1
                continue
            if stat.st_size > max_parse_bytes and path.suffix.lower() in TABLE_EXTENSIONS | DOC_EXTENSIONS | PDF_EXTENSIONS:
                documents.append({
                    "path": rel,
                    "full_path": str(path),
                    "extension": path.suffix.lower(),
                    "mtime": mtime,
                    "size": stat.st_size,
                    "sha1": "",
                })
                errors.append({
                    "path": str(path),
                    "error": f"Skipped large changed/new file over {max_parse_bytes // 1024 // 1024}MB. Existing unchanged files are reused from cache.",
                })
                skipped_large_files += 1
                continue
            doc_hash = file_hash(path)
            documents.append({
                "path": rel,
                "full_path": str(path),
                "extension": path.suffix.lower(),
                "mtime": mtime,
                "size": stat.st_size,
                "sha1": doc_hash,
            })
            file_chunks = chunks_from_file(path, root)
            parsed_docs += 1
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        for chunk_index, chunk in enumerate(file_chunks):
            text = clean_text(chunk.get("text", ""))
            if len(text) < 20:
                continue
            audio_score, sabc, ready_state, sound_type, reason = classify_audio_need(text, rel)
            chunk_id = f"CHK-{short_hash(rel + str(chunk_index) + text[:160])}"
            record = {
                "id": chunk_id,
                "doc_path": rel,
                "full_path": str(path),
                "title": chunk.get("title") or path.stem,
                "locator": chunk.get("locator") or "",
                "text": text[:2400],
                "tokens": sorted(tokenize(f"{rel} {chunk.get('title','')} {text}")),
                "audio_score": audio_score,
                "sabc": sabc,
                "ready_state": ready_state,
                "sound_type": sound_type,
                "reason": reason,
            }
            chunks.append(record)
            if audio_score >= 0.32:
                req_id = f"AR-{short_hash(rel + chunk_id)}"
                requirements.append({
                    "id": req_id,
                    "chunk_id": chunk_id,
                    "doc_path": rel,
                    "full_path": str(path),
                    "title": record["title"],
                    "locator": record["locator"],
                    "feature": infer_feature_name(record["title"], text),
                    "system": infer_system(rel, text),
                    "sound_type": sound_type,
                    "sabc": sabc,
                    "ready_state": ready_state,
                    "audio_score": audio_score,
                    "reason": reason,
                    "evidence": text[:700],
                    "tokens": record["tokens"],
                })

    return {
        "version": INDEX_VERSION,
        "generated_at": now_stamp(),
        "design_root": str(root),
        "documents": documents,
        "chunks": chunks,
        "requirements": requirements,
        "errors": errors,
        "summary": {
            "files_scanned": len(documents),
            "chunks": len(chunks),
            "requirements": len(requirements),
            "errors": len(errors),
            "extensions": dict(Counter(doc["extension"] for doc in documents)),
            "ready_states": dict(Counter(req["ready_state"] for req in requirements)),
            "sound_types": dict(Counter(req["sound_type"] for req in requirements)),
            "reused_docs": reused_docs,
            "parsed_docs": parsed_docs,
            "skipped_large_files": skipped_large_files,
            "max_parse_mb": max_parse_bytes // 1024 // 1024,
        },
    }


def qa_relative_path(path: Path, root: Path) -> str:
    try:
        return normalize_path(path.relative_to(root))
    except ValueError:
        return normalize_path(path)


def qa_generated_roots(root: Path) -> list[Path]:
    root = root.resolve()
    candidates: list[Path] = []
    known = root / "Workspace4Acceptance" / ".qoder" / "generated"
    if known.exists():
        candidates.append(known)
    try:
        for qoder in root.rglob(".qoder"):
            generated = qoder / "generated"
            if generated.exists():
                candidates.append(generated)
    except Exception:
        pass
    if root.name.lower() == "generated" and root.exists():
        candidates.append(root)
    seen: set[str] = set()
    result: list[Path] = []
    for item in candidates:
        key = str(item.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item.resolve())
    return sorted(result, key=lambda item: normalize_path(item).lower())


def qa_testcase_roots(root: Path) -> list[Path]:
    root = root.resolve()
    candidates = [
        root / "QA" / "TestCase",
        root.parent / "QA" / "TestCase",
        root / "ProjectEF_Trunk" / "QA" / "TestCase",
        root.parent / "ProjectEF_Trunk" / "QA" / "TestCase",
    ]
    if root.name.lower() == "testcase" and root.exists():
        candidates.append(root)
    seen: set[str] = set()
    result: list[Path] = []
    for item in candidates:
        try:
            resolved = item.resolve()
        except Exception:
            resolved = item
        key = str(resolved).lower()
        if key in seen or not resolved.exists():
            continue
        seen.add(key)
        result.append(resolved)
    return sorted(result, key=lambda item: normalize_path(item).lower())


def qa_scan_roots(root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    generated_roots = qa_generated_roots(root)
    testcase_roots = qa_testcase_roots(root)
    scan_roots = generated_roots + testcase_roots
    if not scan_roots:
        scan_roots = [root.resolve()]
    seen: set[str] = set()
    deduped: list[Path] = []
    for item in scan_roots:
        key = str(item.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item.resolve())
    return generated_roots, testcase_roots, deduped


def qa_root_is_testcase(root: Path) -> bool:
    return normalize_path(root).lower().endswith("/qa/testcase")


def qa_doc_type(path: Path) -> str:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if path.suffix.lower() == ".xmind":
        return "XMind"
    if "jira_batches" in parts:
        return "JiraBatch"
    if "checklist" in name:
        return "Checklist"
    if "_issues" in name or name.endswith("issues.md"):
        return "Issues"
    if "bug_report" in name:
        return "BugReport"
    if "task_report" in name:
        return "TaskReport"
    return "QADoc"


def qa_system_from_path(path: Path, generated_root: Path) -> str:
    if qa_root_is_testcase(generated_root):
        return path.stem
    try:
        rel = path.relative_to(generated_root)
        if rel.parts:
            return rel.parts[0]
    except ValueError:
        pass
    parent = path.parent
    if parent.name.lower() == "jira_batches":
        return parent.parent.name
    return parent.name


def clean_markdown_inline(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    return clean_text(text)


def clean_qa_heading(text: str) -> str:
    text = clean_markdown_inline(text)
    text = re.sub(r"^\d+[\.\u3001]\s*", "", text)
    text = re.sub(r"^#+\s*", "", text)
    return text.strip(" #\t")


def extract_story_keys(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", text or "")))


def split_qa_refs(text: str) -> list[str]:
    value = clean_markdown_inline(text)
    value = re.sub(r"^\s*>+\s*", "", value)
    value = re.sub(
        r"^\s*(?:\*\*)?(?:\u9a8c\u6536\u4f9d\u636e|\u7b56\u5212\u6848\u6eaf\u6e90|\u7b56\u5212\u6848\u7248\u672c)(?:\*\*)?\s*[:\uff1a]\s*",
        "",
        value,
    )
    value = value.strip()
    if not value:
        return []
    parts = re.split(r"\s*\+\s*|\s*[;\uff1b]\s*", value)
    return [part.strip(" -\t") for part in parts if part.strip(" -\t")]


def extract_acceptance_refs(text: str) -> list[str]:
    refs: list[str] = []
    for line in (text or "").splitlines():
        if "\u9a8c\u6536\u4f9d\u636e" in line:
            refs.extend(split_qa_refs(line))
    return sorted(set(refs))


def extract_trace_refs(text: str) -> list[str]:
    refs: list[str] = []
    for line in (text or "").splitlines():
        if "\u7b56\u5212\u6848\u6eaf\u6e90" in line:
            refs.extend(split_qa_refs(line))
    return sorted(set(refs))


def qa_source_refs_from_case_body(body: str) -> tuple[str, list[str]]:
    parts = re.split(r"\s*\U0001f4ce\s*", body, maxsplit=1)
    if len(parts) == 1:
        return clean_markdown_inline(body), []
    return clean_markdown_inline(parts[0]), split_qa_refs(parts[1])


def derive_qa_steps_and_expected(body: str) -> tuple[str, list[str], str]:
    body = clean_markdown_inline(body)
    if not body:
        return "", [], ""
    arrow_parts = [part.strip() for part in re.split(r"\s*(?:->|=>|\u2192|\u21d2)\s*", body) if part.strip()]
    if len(arrow_parts) >= 2:
        prefix = ""
        for sep in ("\uff1a", ":"):
            if sep in arrow_parts[0]:
                prefix, first_step = arrow_parts[0].split(sep, 1)
                arrow_parts[0] = first_step.strip()
                break
        test_point = prefix.strip() or body
        return test_point, arrow_parts[:-1], arrow_parts[-1]

    operation_words = {
        "\u70b9\u51fb",
        "\u89e6\u53d1",
        "\u8fdb\u5165",
        "\u6253\u5f00",
        "\u5173\u95ed",
        "\u5207\u6362",
        "\u8fbe\u6210",
        "\u6ee1\u8db3",
        "\u5b8c\u6210",
        "\u5236\u9020",
        "\u51c6\u5907",
        "\u9000\u51fa",
        "\u91cd\u65b0",
    }
    for sep in ("\uff0c", ","):
        if sep in body:
            left, right = body.split(sep, 1)
            left = left.strip()
            right = right.strip()
            if left and right and (any(word in left for word in operation_words) or left.endswith(("\u65f6", "\u540e"))):
                return body, [left], right
    return body, [], ""


def qa_case_kind(section: str) -> str:
    section = section or ""
    if "\u5192\u70df" in section:
        return "Smoke"
    if "\u7aef\u5230\u7aef" in section or "\u62bd\u67e5" in section or "\u590d\u5408\u94fe\u8def" in section:
        return "E2E"
    if "\u6837\u4f8b" in section:
        return "Sample"
    return "Checklist"


def should_parse_qa_section(section: str) -> bool:
    if not section:
        return True
    blocked = (
        "\u5f85\u786e\u8ba4",
        "\u4f7f\u7528\u8bf4\u660e",
        "\u6587\u6863\u76ee\u7684",
        "\u5efa\u8bae\u9a8c\u6536\u987a\u5e8f",
    )
    return not any(token in section for token in blocked)


def parse_qa_checklist_cases(text: str, path: Path, root: Path, doc: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    rel = doc.get("path") or qa_relative_path(path, root)
    doc_title = doc.get("title") or path.stem
    acceptance_refs = list(doc.get("acceptance_refs") or [])
    current_h2 = ""
    current_h3 = ""
    checkbox = re.compile(r"^\s*[-*]\s*\[(?P<checked>[ xX])\]\s*(?P<body>.+?)\s*$")
    heading = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
    priority_re = re.compile(r"^\[(P[0-5])\]\s*", re.I)
    for line_no, raw_line in enumerate((text or "").splitlines(), 1):
        line = raw_line.rstrip()
        heading_match = heading.match(line)
        if heading_match:
            level = len(heading_match.group("marks"))
            title = clean_qa_heading(heading_match.group("title"))
            if level == 1:
                doc_title = title or doc_title
            elif level == 2:
                current_h2 = title
                current_h3 = ""
            elif level == 3:
                current_h3 = title
            continue
        match = checkbox.match(line)
        if not match or not should_parse_qa_section(current_h2):
            continue
        status = "Done" if match.group("checked").strip().lower() == "x" else "Open"
        body, source_refs = qa_source_refs_from_case_body(match.group("body"))
        priority = ""
        priority_match = priority_re.match(body)
        if priority_match:
            priority = priority_match.group(1).upper()
            body = body[priority_match.end() :].strip()
        test_point, operation_steps, expected_result = derive_qa_steps_and_expected(body)
        feature_point = current_h3 or current_h2 or doc_title
        design_refs = sorted(set(acceptance_refs + source_refs))
        case_id = f"QA-{short_hash(rel + str(line_no) + body)}"
        token_text = " ".join(
            str(part)
            for part in (
                rel,
                doc_title,
                doc.get("system", ""),
                current_h2,
                feature_point,
                test_point,
                " ".join(operation_steps),
                expected_result,
                " ".join(design_refs),
            )
        )
        cases.append({
            "id": case_id,
            "doc_id": doc.get("id", ""),
            "doc_path": rel,
            "full_path": str(path),
            "doc_title": doc_title,
            "system": doc.get("system", ""),
            "section": current_h2,
            "kind": qa_case_kind(current_h2),
            "feature_point": feature_point,
            "test_point": test_point,
            "operation_steps": operation_steps,
            "expected_result": expected_result,
            "status": status,
            "priority": priority,
            "source_refs": source_refs,
            "design_refs": design_refs,
            "story_keys": list(doc.get("story_keys") or []),
            "locator": f"line {line_no}",
            "raw": body,
            "tokens": sorted(tokenize(token_text)),
        })
    return cases


def xmind_clean_title(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"^\s*(?:\[[^\]]+\]|\u3010[^\u3011]+\u3011)\s*", "", text).strip()
    return text or clean_text(text)


def xmind_json_children(topic: dict[str, Any]) -> list[dict[str, Any]]:
    children = topic.get("children")
    result: list[dict[str, Any]] = []
    if not isinstance(children, dict):
        return result
    for value in children.values():
        if isinstance(value, list):
            result.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            attached = value.get("attached")
            if isinstance(attached, list):
                result.extend(item for item in attached if isinstance(item, dict))
            detached = value.get("detached")
            if isinstance(detached, list):
                result.extend(item for item in detached if isinstance(item, dict))
    return result


def xmind_json_title(topic: dict[str, Any]) -> str:
    title = str(topic.get("title") or "").strip()
    if title:
        return title
    attributed = topic.get("attributedTitle")
    if isinstance(attributed, list):
        title = "".join(str(part.get("text") or "") for part in attributed if isinstance(part, dict)).strip()
    return title


def xmind_json_markers(topic: dict[str, Any]) -> list[str]:
    markers = topic.get("markers")
    if not isinstance(markers, list):
        return []
    result: list[str] = []
    for marker in markers:
        if isinstance(marker, dict) and marker.get("markerId"):
            result.append(str(marker.get("markerId")))
    return result


def parse_xmind_json_topics(data: Any) -> list[dict[str, Any]]:
    sheets = data if isinstance(data, list) else [data]
    topics: list[dict[str, Any]] = []

    def walk(topic: dict[str, Any], ancestors: list[str], depth: int) -> None:
        title = xmind_json_title(topic)
        children = xmind_json_children(topic)
        if title:
            path_titles = ancestors + [title]
            topics.append({
                "title": title,
                "path_titles": path_titles,
                "depth": depth,
                "has_children": bool(children),
                "markers": xmind_json_markers(topic),
            })
            next_ancestors = path_titles
        else:
            next_ancestors = ancestors
        for child in children:
            walk(child, next_ancestors, depth + 1)

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        root_topic = sheet.get("rootTopic") or sheet.get("root-topic")
        if isinstance(root_topic, dict):
            walk(root_topic, [], 0)
    return topics


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def xmind_xml_topic_title(topic: ElementTree.Element) -> str:
    for child in topic:
        if xml_local_name(child.tag) == "title":
            return "".join(child.itertext()).strip()
    return str(topic.attrib.get("title") or "").strip()


def xmind_xml_topic_children(topic: ElementTree.Element) -> list[ElementTree.Element]:
    result: list[ElementTree.Element] = []
    for child in topic:
        if xml_local_name(child.tag) != "children":
            continue
        for topics_node in child:
            if xml_local_name(topics_node.tag) != "topics":
                continue
            for item in topics_node:
                if xml_local_name(item.tag) == "topic":
                    result.append(item)
    return result


def parse_xmind_xml_topics(xml_bytes: bytes) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except Exception:
        return []
    topics: list[dict[str, Any]] = []

    def walk(topic: ElementTree.Element, ancestors: list[str], depth: int) -> None:
        title = xmind_xml_topic_title(topic)
        children = xmind_xml_topic_children(topic)
        if title:
            path_titles = ancestors + [title]
            topics.append({
                "title": title,
                "path_titles": path_titles,
                "depth": depth,
                "has_children": bool(children),
                "markers": [],
            })
            next_ancestors = path_titles
        else:
            next_ancestors = ancestors
        for child in children:
            walk(child, next_ancestors, depth + 1)

    roots: list[ElementTree.Element] = []
    for sheet in root.iter():
        if xml_local_name(sheet.tag) != "sheet":
            continue
        for child in sheet:
            if xml_local_name(child.tag) == "topic":
                roots.append(child)
    if not roots and xml_local_name(root.tag) == "topic":
        roots.append(root)
    for topic in roots:
        walk(topic, [], 0)
    return topics


def read_xmind_topics(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "content.json" in names:
                data = json.loads(archive.read("content.json").decode("utf-8", errors="replace"))
                topics = parse_xmind_json_topics(data)
                title = topics[0]["title"] if topics else path.stem
                return title, topics
            if "content.xml" in names:
                topics = parse_xmind_xml_topics(archive.read("content.xml"))
                title = topics[0]["title"] if topics else path.stem
                return title, topics
    except Exception:
        return path.stem, []
    return path.stem, []


def xmind_topic_status(markers: list[str]) -> str:
    marker_text = " ".join(markers).lower()
    if "task-done" in marker_text or "task-complete" in marker_text:
        return "Done"
    return "Open"


def xmind_case_kind(path_titles: list[str], file_name: str) -> str:
    hay = " ".join(path_titles + [file_name]).lower()
    if "smoke" in hay or "\u5192\u70df" in hay:
        return "Smoke"
    if "case" in hay or "\u7528\u4f8b" in hay:
        return "Checklist"
    if "fc" in hay:
        return "FC"
    return "XMind"


def parse_qa_xmind_cases(path: Path, root: Path, doc: dict[str, Any], topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    rel = doc.get("path") or qa_relative_path(path, root)
    doc_title = doc.get("title") or path.stem
    acceptance_refs = list(doc.get("acceptance_refs") or [])
    candidates = [topic for topic in topics if topic.get("depth", 0) > 0 and not topic.get("has_children")]
    if not candidates:
        candidates = [topic for topic in topics if topic.get("depth", 0) > 0]
    for case_index, topic in enumerate(candidates, 1):
        raw_title = clean_text(str(topic.get("title") or ""))
        if not raw_title:
            continue
        path_titles = [clean_text(str(item)) for item in topic.get("path_titles") or [] if clean_text(str(item))]
        ancestors = path_titles[:-1]
        body = xmind_clean_title(raw_title)
        priority = ""
        priority_match = re.match(r"^\[(P[0-5])\]\s*", body, re.I)
        if priority_match:
            priority = priority_match.group(1).upper()
            body = body[priority_match.end() :].strip()
        test_point, operation_steps, expected_result = derive_qa_steps_and_expected(body)
        if not operation_steps and ancestors:
            previous = xmind_clean_title(ancestors[-1])
            if previous and previous != body:
                operation_steps = [previous]
        if not expected_result and re.search(r"(?:\bCP\b|\u3010CP\u3011|\[CP\])", raw_title, re.I):
            expected_result = body
            if ancestors:
                test_point = xmind_clean_title(ancestors[-1])
        feature_point = ""
        for ancestor in reversed(ancestors):
            if "\u3010Case\u3011" in ancestor or "[Case]" in ancestor:
                feature_point = xmind_clean_title(ancestor)
                break
        if not feature_point:
            feature_point = xmind_clean_title(ancestors[-1]) if ancestors else doc_title
        design_refs = sorted(set(acceptance_refs))
        case_id = f"QA-{short_hash(rel + str(case_index) + '>'.join(path_titles))}"
        token_text = " ".join(
            str(part)
            for part in (
                rel,
                doc_title,
                doc.get("system", ""),
                " ".join(path_titles),
                feature_point,
                test_point,
                " ".join(operation_steps),
                expected_result,
            )
        )
        cases.append({
            "id": case_id,
            "doc_id": doc.get("id", ""),
            "doc_path": rel,
            "full_path": str(path),
            "doc_title": doc_title,
            "system": doc.get("system", ""),
            "section": xmind_clean_title(ancestors[1]) if len(ancestors) > 1 else doc_title,
            "kind": xmind_case_kind(path_titles, path.name),
            "feature_point": feature_point,
            "test_point": test_point,
            "operation_steps": operation_steps,
            "expected_result": expected_result,
            "status": xmind_topic_status(list(topic.get("markers") or [])),
            "priority": priority,
            "source_refs": [],
            "design_refs": design_refs,
            "story_keys": list(doc.get("story_keys") or []),
            "locator": f"xmind topic {case_index}",
            "raw": " > ".join(path_titles),
            "tokens": sorted(tokenize(token_text)),
        })
    return cases


def build_qa_acceptance_index(root: Path, progress=None) -> dict[str, Any]:
    root = root.resolve()
    generated_roots, testcase_roots, scan_roots = qa_scan_roots(root)
    files: list[tuple[Path, Path]] = []
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in QA_SOURCE_EXTENSIONS:
                files.append((path, scan_root))
    files.sort(key=lambda item: normalize_path(item[0]).lower())

    documents: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    doc_by_id: dict[str, dict[str, Any]] = {}
    cases_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    system_story_keys: dict[str, set[str]] = defaultdict(set)

    for file_index, (path, generated_root) in enumerate(files, 1):
        if progress:
            progress(f"Scanning QA {file_index}/{len(files)}: {path.name}")
        try:
            suffix = path.suffix.lower()
            xmind_topics: list[dict[str, Any]] = []
            if suffix == ".xmind":
                xmind_title, xmind_topics = read_xmind_topics(path)
                text = "\n".join(str(topic.get("title") or "") for topic in xmind_topics)
            else:
                xmind_title = ""
                text = read_text_file(path)
            stat = path.stat()
            rel = qa_relative_path(path, root)
            title_match = re.search(r"^\s*#\s+(.+?)\s*$", text, re.M)
            title = xmind_title or (clean_qa_heading(title_match.group(1)) if title_match else path.stem)
            system = qa_system_from_path(path, generated_root)
            story_keys = extract_story_keys(text)
            acceptance_refs = extract_acceptance_refs(text)
            trace_refs = extract_trace_refs(text)
            doc_id = f"QADOC-{short_hash(rel)}"
            doc = {
                "id": doc_id,
                "path": rel,
                "full_path": str(path),
                "title": title,
                "system": system,
                "doc_type": qa_doc_type(path),
                "generated_root": str(generated_root),
                "mtime": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "size": stat.st_size,
                "sha1": file_hash(path),
                "story_keys": story_keys,
                "story_key_source": "Explicit" if story_keys else "",
                "acceptance_refs": acceptance_refs,
                "trace_refs": trace_refs,
                "tokens": sorted(tokenize(f"{rel} {title} {system} {' '.join(acceptance_refs)} {' '.join(trace_refs)}")),
                "case_count": 0,
            }
            if doc["doc_type"] == "XMind":
                parsed_cases = parse_qa_xmind_cases(path, root, doc, xmind_topics)
            elif doc["doc_type"] == "Checklist":
                parsed_cases = parse_qa_checklist_cases(text, path, root, doc)
            else:
                parsed_cases = []
            documents.append(doc)
            doc_by_id[doc_id] = doc
            if story_keys:
                system_story_keys[system].update(story_keys)
            for case in parsed_cases:
                cases.append(case)
                cases_by_doc[doc_id].append(case)
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})

    for doc in documents:
        inferred_keys = sorted(system_story_keys.get(doc.get("system", ""), set()))
        if not doc.get("story_keys") and inferred_keys:
            doc["story_keys"] = inferred_keys
            doc["story_key_source"] = "InferredBySystem"
        doc["case_count"] = len(cases_by_doc.get(doc["id"], []))

    for case in cases:
        doc = doc_by_id.get(case.get("doc_id", ""))
        if doc:
            case["story_keys"] = list(doc.get("story_keys") or [])
            case["story_key_source"] = doc.get("story_key_source", "")

    by_story: dict[str, dict[str, Any]] = {}
    for doc in documents:
        for key in doc.get("story_keys") or []:
            entry = by_story.setdefault(key, {"doc_ids": [], "case_ids": []})
            entry["doc_ids"].append(doc["id"])
    for case in cases:
        for key in case.get("story_keys") or []:
            entry = by_story.setdefault(key, {"doc_ids": [], "case_ids": []})
            entry["case_ids"].append(case["id"])
    for entry in by_story.values():
        entry["doc_ids"] = sorted(set(entry["doc_ids"]))
        entry["case_ids"] = sorted(set(entry["case_ids"]))

    return {
        "version": QA_INDEX_VERSION,
        "generated_at": now_stamp(),
        "design_root": str(root),
        "generated_roots": [str(item) for item in generated_roots],
        "testcase_roots": [str(item) for item in testcase_roots],
        "scan_roots": [str(item) for item in scan_roots],
        "documents": documents,
        "cases": cases,
        "cases_by_doc": {
            doc_id: [case.get("id", "") for case in doc_cases]
            for doc_id, doc_cases in cases_by_doc.items()
        },
        "by_story": by_story,
        "errors": errors,
        "summary": {
            "files_scanned": len(documents),
            "cases": len(cases),
            "errors": len(errors),
            "systems": dict(Counter(doc.get("system", "") for doc in documents)),
            "doc_types": dict(Counter(doc.get("doc_type", "") for doc in documents)),
            "case_statuses": dict(Counter(case.get("status", "") for case in cases)),
            "case_kinds": dict(Counter(case.get("kind", "") for case in cases)),
            "story_keys": len(by_story),
        },
    }


def load_qa_index() -> dict[str, Any]:
    if not QA_INDEX_PATH.exists():
        return {}
    index = json.loads(QA_INDEX_PATH.read_text(encoding="utf-8"))
    return ensure_qa_index_lookup(index)


def save_qa_index(index: dict[str, Any]) -> None:
    ensure_qa_index_lookup(index)
    payload = {key: value for key, value in index.items() if not str(key).startswith("_")}
    QA_INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_qa_index_lookup(index: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(index, dict):
        return {}
    if not isinstance(index.get("_case_by_id"), dict):
        index["_case_by_id"] = {
            str(case.get("id") or ""): case
            for case in index.get("cases", []) or []
            if isinstance(case, dict) and case.get("id")
        }
    cases_by_doc = index.get("cases_by_doc")
    if not isinstance(cases_by_doc, dict):
        grouped: dict[str, list[str]] = defaultdict(list)
        for case in index.get("cases", []) or []:
            if not isinstance(case, dict):
                continue
            doc_id = str(case.get("doc_id") or "")
            case_id = str(case.get("id") or "")
            if doc_id and case_id:
                grouped[doc_id].append(case_id)
        index["cases_by_doc"] = dict(grouped)
    if not isinstance(index.get("_topic_docs"), list) and "qa_topic_tokens" in globals():
        topic_docs: list[tuple[dict[str, Any], set[str]]] = []
        for doc in index.get("documents", []) or []:
            if isinstance(doc, dict):
                topic_docs.append((doc, qa_topic_tokens(qa_doc_topic_text(doc))))
        index["_topic_docs"] = topic_docs
    return index


def qa_cases_for_doc_ids(qa_index: dict[str, Any], doc_ids: set[str]) -> list[dict[str, Any]]:
    if not doc_ids:
        return list(qa_index.get("cases", []) or [])
    ensure_qa_index_lookup(qa_index)
    case_by_id = qa_index.get("_case_by_id") if isinstance(qa_index.get("_case_by_id"), dict) else {}
    cases_by_doc = qa_index.get("cases_by_doc")
    if isinstance(cases_by_doc, dict) and case_by_id:
        result: list[dict[str, Any]] = []
        for doc_id in doc_ids:
            for case_id in cases_by_doc.get(doc_id, []) or []:
                case = case_by_id.get(str(case_id))
                if case:
                    result.append(case)
        return result
    return [
        case
        for case in qa_index.get("cases", []) or []
        if isinstance(case, dict) and str(case.get("doc_id") or "") in doc_ids
    ]


def jira_field_matches_qa_hint(field: dict[str, Any]) -> bool:
    hay = f"{field.get('id','')} {field.get('name','')}".lower()
    return any(hint.lower() in hay for hint in JIRA_QA_FIELD_HINTS)


def flatten_jira_strings(value: Any, depth: int = 0) -> list[str]:
    if depth > 5 or value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_jira_strings(item, depth + 1))
        return result
    if isinstance(value, dict):
        result = []
        for key in ("name", "value", "displayName", "filename", "content", "title", "text"):
            if key in value:
                result.extend(flatten_jira_strings(value.get(key), depth + 1))
        return result
    return []


def looks_like_qa_ref(text: str) -> bool:
    if not text:
        return False
    hay = normalize_path(text).lower()
    return (
        any(hint.lower() in hay for hint in JIRA_QA_FIELD_HINTS)
        or "workspace4acceptance" in hay
        or ".qoder" in hay
        or "qa/testcase" in hay
        or "projectef_trunk/qa/testcase" in hay
        or "checklist" in hay
        or re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", text) is not None
    )


def extract_path_like_qa_refs(text: str) -> list[str]:
    if not text:
        return []
    refs: list[str] = []
    ext_pattern = "|".join(re.escape(ext.lstrip(".")) for ext in QA_PATH_EXTENSIONS)
    patterns = [
        rf"(?:[A-Za-z]:[\\/][^\s<>\"|]+?\.({ext_pattern}))",
        r"(?:ProjectEF_Trunk[\\/](?:QA|qa)[\\/](?:TestCase|testcase)[^\r\n<>\"|]*)",
        r"(?:(?:QA|qa)[\\/](?:TestCase|testcase)[^\r\n<>\"|]*)",
        rf"(?:Workspace4Acceptance[\\/][^\s<>\"|]+?\.({ext_pattern}))",
        rf"(?:\.qoder[\\/][^\s<>\"|]+?\.({ext_pattern}))",
        rf"(?:generated[\\/][^\s<>\"|]+?\.({ext_pattern}))",
        rf"(?:[\w\u4e00-\u9fff ._()-]+[\\\/][\w\u4e00-\u9fff ._()\\\/-]+?\.({ext_pattern}))",
        rf"(?:[\w\u4e00-\u9fff ._()-]*?(?:Checklist|checklist|\u7528\u4f8b|\u9a8c\u6536)[\w\u4e00-\u9fff ._()-]*?\.({ext_pattern}))",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = match.group(0).strip(" \t\r\n，,；;。.)]】>\"'")
            for sep in ("：", ":"):
                if sep in value:
                    tail = value.split(sep)[-1].strip()
                    if "/" in tail or "\\" in tail:
                        value = tail
            refs.append(value)
    return dedupe_refs_prefer_full_paths(refs)


def split_possible_jira_qa_refs(text: str) -> list[str]:
    text = clean_text(text)
    refs: list[str] = []
    refs.extend(re.findall(r"https?://[^\s<>\"]+", text))
    refs.extend(re.findall(r"[A-Za-z]:[\\/][^\s<>\"]+", text))
    refs.extend(extract_path_like_qa_refs(text))
    for line in text.splitlines():
        line = clean_text(line)
        if not line:
            continue
        line_path_refs = extract_path_like_qa_refs(line)
        if line_path_refs:
            refs.extend(line_path_refs)
            continue
        if looks_like_qa_ref(line):
            refs.append(line[:500])
    return dedupe_keep_order(refs)


def extract_jira_qa_refs(fields: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key, value in fields.items():
        is_likely_field = key == "attachment" or key.startswith("customfield_")
        for text in flatten_jira_strings(value):
            if is_likely_field or looks_like_qa_ref(text):
                refs.extend(split_possible_jira_qa_refs(text))
    return dedupe_refs_prefer_full_paths(refs)[:80]


def qa_ref_match_candidates(ref: str) -> list[str]:
    raw_refs = [ref] + extract_path_like_qa_refs(ref)
    candidates: list[str] = []

    def is_specific(candidate: str) -> bool:
        value = candidate.strip().lower()
        if len(value) < 4:
            return False
        if value.count("?") >= 2:
            return False
        generic = {
            "checklist",
            "_checklist",
            "issues",
            "_issues",
            "testcase",
            "test_case",
            "testcases",
            "test_cases",
        }
        if value in generic:
            return False
        if value.endswith("_checklist") and len(value) <= len("_checklist") + 2:
            return False
        if value.endswith("_issues") and len(value) <= len("_issues") + 2:
            return False
        return True

    for raw in raw_refs:
        norm = normalize_path(str(raw or "")).lower().strip()
        if not norm:
            continue
        if is_specific(norm):
            candidates.append(norm)
        ref_name = re.split(r"[\\/]", norm.rstrip("/"))[-1]
        if ref_name and is_specific(ref_name):
            candidates.append(ref_name)
        stem = Path(ref_name).stem.lower()
        if stem and is_specific(stem):
            candidates.append(stem)
    for key in re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", ref or ""):
        candidates.append(key.lower())
    return dedupe_keep_order(candidate for candidate in candidates if is_specific(candidate))


def qa_ref_matches_document(ref: str, doc: dict[str, Any]) -> bool:
    if not ref:
        return False
    hay = normalize_path(" ".join(str(doc.get(key, "")) for key in ("path", "full_path", "title"))).lower()
    story_keys = {str(key).lower() for key in doc.get("story_keys") or []}
    for candidate in qa_ref_match_candidates(ref):
        if candidate in story_keys or candidate in hay:
            return True
    return False


def qa_documents_matching_refs(qa_index: dict[str, Any], refs: list[str]) -> list[dict[str, Any]]:
    if not refs:
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in qa_index.get("documents", []):
        if not isinstance(doc, dict):
            continue
        if any(qa_ref_matches_document(ref, doc) for ref in refs):
            doc_id = str(doc.get("id", ""))
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                result.append(doc)
    return result


QA_TOPIC_STOP_TOKENS = {
    "fc",
    "module",
    "moudle",
    "smoke",
    "qa",
    "test",
    "case",
    "testcase",
    "projectef",
    "trunk",
    "design",
    "new",
    "xmind",
    "md",
    "ui",
    "gameplay",
    "fishing",
    "items",
    "progression",
    "功能",
    "系统",
    "测试",
    "用例",
    "设计",
    "文档",
    "策划",
    "界面",
    "交互",
    "模块",
    "关卡",
    "系统关卡",
    "功能文档",
    "策划文档",
    "测试用例",
    "音效",
    "音频",
    "声音",
    "制作",
    "配置",
    "调试",
    "入版",
}


def path_stem_text(value: Any) -> str:
    text = normalize_path(str(value or "")).strip()
    if not text:
        return ""
    return Path(text).stem


def qa_topic_tokens(text: str) -> set[str]:
    normalized = normalize_path(text).lower()
    normalized = re.sub(r"【[^】]*】|\[[^\]]*\]", " ", normalized)
    tokens = tokenize(normalized)
    return {
        token
        for token in tokens
        if token not in QA_TOPIC_STOP_TOKENS
        and not token.isdigit()
        and len(token) >= 2
    }


def qa_issue_topic_text(issue: dict[str, Any], evidence: list[dict[str, Any]] | None = None) -> str:
    parts = [
        issue.get("summary", ""),
        issue.get("description", ""),
        issue.get("system", ""),
        issue.get("design_area", ""),
        path_stem_text(issue.get("design_doc", "")),
    ]
    for item in evidence or []:
        parts.extend([
            item.get("system", ""),
            item.get("title", ""),
            item.get("feature", ""),
            path_stem_text(item.get("doc_path", "")),
        ])
    return " ".join(str(part) for part in parts if str(part).strip())


def qa_doc_topic_text(doc: dict[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in (
            doc.get("system", ""),
            doc.get("title", ""),
            path_stem_text(doc.get("path", "")),
            path_stem_text(doc.get("full_path", "")),
        )
        if str(part).strip()
    )


def qa_documents_matching_issue_topic(
    qa_index: dict[str, Any],
    issue: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    ensure_qa_index_lookup(qa_index)
    query_text = qa_issue_topic_text(issue, evidence)
    query_tokens = qa_topic_tokens(query_text)
    if not query_tokens:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    topic_docs = qa_index.get("_topic_docs") if isinstance(qa_index.get("_topic_docs"), list) else []
    if not topic_docs:
        topic_docs = [
            (doc, qa_topic_tokens(qa_doc_topic_text(doc)))
            for doc in qa_index.get("documents", []) or []
            if isinstance(doc, dict)
        ]
        qa_index["_topic_docs"] = topic_docs
    for doc, doc_tokens in topic_docs:
        overlap = query_tokens & doc_tokens
        if not overlap:
            continue
        score = float(len(overlap))
        if "图鉴" in overlap:
            score += 3.0
        if any(token.endswith("图鉴") for token in overlap):
            score += 2.0
        if "排行榜" in overlap:
            score += 3.0
        if "鱼系统" in overlap:
            score += 0.6
        doc_path = normalize_path(str(doc.get("path") or doc.get("full_path") or "")).lower()
        if "qa/testcase" in doc_path:
            score += 0.4
        if score >= 1.4 or "图鉴" in overlap or "排行榜" in overlap:
            scored.append((score, doc))
    scored.sort(key=lambda item: (item[0], len(str(item[1].get("path") or ""))), reverse=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _score, doc in scored:
        doc_id = str(doc.get("id") or doc.get("full_path") or doc.get("path") or "")
        if doc_id in seen:
            continue
        seen.add(doc_id)
        result.append(doc)
        if len(result) >= limit:
            break
    return result


def summarize_qa_path_from_cases(cases: list[dict[str, Any]], fallback_refs: list[str] | None = None, limit: int = 2) -> str:
    paths: list[str] = []
    for case in cases:
        path = str(case.get("doc_path") or case.get("full_path") or "").strip()
        if path:
            paths.append(path)
    if not paths and fallback_refs:
        paths.extend(str(ref) for ref in fallback_refs if str(ref).strip())
    deduped = dedupe_keep_order(paths)
    if not deduped:
        return ""
    label = " | ".join(deduped[:limit])
    if len(deduped) > limit:
        label += f" | +{len(deduped) - limit} more"
    return label


def qa_ref_path_variants(candidate: str) -> list[str]:
    normalized = normalize_path(candidate).strip().lstrip("/")
    if not normalized:
        return []
    variants = [normalized]
    lowered = normalized.lower()
    trunk_prefix = "projectef_trunk/"
    if lowered.startswith(trunk_prefix):
        variants.append(normalized[len(trunk_prefix) :])
    qa_index = lowered.find("qa/testcase")
    if qa_index >= 0:
        variants.append(normalized[qa_index:])
    return dedupe_keep_order(variants)


def qa_name_match_score(target_name: str, file_name: str) -> float:
    target_stem = Path(target_name).stem
    file_stem = Path(file_name).stem
    target_norm = normalize_path(target_stem).lower()
    file_norm = normalize_path(file_stem).lower()
    target_flat = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", target_norm)
    file_flat = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", file_norm)
    score = 0.0
    if target_flat and target_flat in file_flat:
        score += 2.0
    generic_tokens = globals().get("GENERIC_QA_SYSTEM_TOKENS", set())
    target_tokens = {token for token in tokenize(target_stem) if token not in generic_tokens}
    file_tokens = {token for token in tokenize(file_stem) if token not in generic_tokens}
    if target_tokens and file_tokens:
        overlap = target_tokens & file_tokens
        score += len(overlap) / max(1, len(target_tokens))
        if "fc" in target_tokens and "fc" in file_tokens:
            score += 0.6
        if "module" in target_tokens and "module" in file_tokens:
            score += 0.4
    return score


def qa_fuzzy_existing_path(path: Path) -> str:
    if path.exists():
        return str(path)
    parent = path.parent
    target_name = path.name
    if not target_name or not parent.exists():
        return ""
    scored: list[tuple[float, str]] = []
    try:
        children = list(parent.iterdir())
    except Exception:
        return ""
    for child in children:
        if not child.is_file() or child.suffix.lower() not in QA_PATH_EXTENSIONS:
            continue
        score = qa_name_match_score(target_name, child.name)
        if score >= 0.65:
            scored.append((score, str(child)))
    if not scored:
        return ""
    scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return scored[0][1]


def qa_ref_existing_paths(ref: str, design_root: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    for variant in qa_ref_path_variants(ref):
        path = Path(variant)
        candidates.append(path)
        if design_root is None:
            continue
        bases = [design_root, design_root.parent]
        for base in bases:
            candidates.append(base / variant)
    seen: set[str] = set()
    result: list[Path] = []
    for path in candidates:
        key = normalize_path(path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def qa_ref_open_target(ref: str, design_root: Path | None = None) -> str:
    value = clean_text(str(ref or "")).strip()
    if not value:
        return ""
    url_match = re.search(r"https?://[^\s<>\"]+", value)
    if url_match:
        return url_match.group(0).strip(" \t\r\n，,；;。.)]】>\"'")
    path_refs = extract_path_like_qa_refs(value) or [value]
    for candidate in path_refs:
        candidate = candidate.strip(" \t\r\n，,；;。.)]】>\"'")
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return str(path)
        for possible_path in qa_ref_existing_paths(candidate, design_root):
            fuzzy_path = qa_fuzzy_existing_path(possible_path)
            if fuzzy_path:
                return fuzzy_path
        if design_root is not None:
            normalized = normalize_path(candidate).lstrip("/")
            root_candidate = design_root / normalized
            if root_candidate.exists():
                return str(root_candidate)
            if normalized.lower().startswith("workspace4acceptance/"):
                root_candidate = design_root / normalized
                if root_candidate.exists():
                    return str(root_candidate)
        if any(candidate.lower().endswith(ext) for ext in QA_PATH_EXTENSIONS):
            return candidate
    return ""


def first_qa_open_target(cases: list[dict[str, Any]], fallback_refs: list[str] | None = None, design_root: Path | None = None) -> str:
    for case in cases:
        full_path = str(case.get("full_path") or "").strip()
        if full_path and Path(full_path).exists():
            return full_path
    for ref in fallback_refs or []:
        target = qa_ref_open_target(str(ref), design_root)
        if target:
            return target
    return ""


def evidence_affinity_for_qa_case(case: dict[str, Any], evidence: dict[str, Any]) -> float:
    if not evidence:
        return 0.0
    evidence_text = " ".join(
        str(evidence.get(key, ""))
        for key in ("doc_path", "title", "locator", "feature", "evidence", "text")
    )
    evidence_tokens = tokenize(evidence_text)
    case_affinity_text = " ".join(
        str(part)
        for part in (
            case.get("section", ""),
            case.get("feature_point", ""),
            case.get("test_point", ""),
            " ".join(case.get("operation_steps") or []),
            case.get("expected_result", ""),
            " ".join(case.get("source_refs") or []),
        )
    )
    case_tokens = tokenize(case_affinity_text)
    if not evidence_tokens or not case_tokens:
        overlap_score = 0.0
    else:
        overlap_score = min(0.5, len(evidence_tokens & case_tokens) / max(8, min(len(evidence_tokens), len(case_tokens))))
    refs = case.get("source_refs") or case.get("design_refs") or []
    refs_text = normalize_path(" ".join(str(ref) for ref in refs)).lower()
    doc_stem = Path(str(evidence.get("doc_path", ""))).stem.lower()
    stem_score = 0.0
    if doc_stem and doc_stem in refs_text:
        stem_score += 0.45
    for token in tokenize(doc_stem):
        if token in refs_text:
            stem_score += 0.08
    base_score = overlap_score + min(0.45, stem_score)
    system_score = 0.05 if base_score > 0 and case.get("system") and str(case.get("system")) in evidence_text else 0.0
    return min(1.0, base_score + system_score)


GENERIC_QA_SYSTEM_TOKENS = {
    "系统",
    "功能",
    "模块",
    "玩法",
    "测试",
    "用例",
    "验收",
    "checklist",
}


def qa_document_system_matches_issue(doc: dict[str, Any], query: str, evidence: list[dict[str, Any]]) -> bool:
    system = str(doc.get("system") or "").strip()
    if not system:
        return True
    hay = " ".join(
        [query]
        + [
            " ".join(
                str(item.get(key, ""))
                for key in ("doc_path", "title", "feature", "evidence", "text", "system")
            )
            for item in evidence
        ]
    )
    hay_norm = normalize_path(hay).lower()
    system_norm = normalize_path(system).lower()
    if system_norm and system_norm in hay_norm:
        return True
    system_tokens = {
        token
        for token in tokenize(system)
        if token not in GENERIC_QA_SYSTEM_TOKENS and len(token) >= 2
    }
    if not system_tokens:
        return True
    hay_tokens = tokenize(hay)
    return bool(system_tokens & hay_tokens)


def qa_priority_sort_value(case: dict[str, Any]) -> int:
    priority = str(case.get("priority") or "").upper()
    if priority.startswith("P") and priority[1:].isdigit():
        return int(priority[1:])
    return 9


def rank_qa_cases_for_issue(
    issue: dict[str, Any],
    qa_index: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    if not qa_index:
        return []
    ensure_qa_index_lookup(qa_index)
    evidence = evidence or []
    linked_qa_text = " ".join(
        " ".join(str(item.get(key, "")) for key in ("key", "summary", "status", "relation"))
        for item in (issue.get("qa_design_issues") or [])
        if isinstance(item, dict)
    )
    qa_detail_text = " ".join(
        " ".join(
            [
                str(item.get("key", "")),
                str(item.get("summary", "")),
                " ".join(str(ref) for ref in item.get("refs") or []),
            ]
        )
        for item in (issue.get("qa_design_details") or [])
        if isinstance(item, dict)
    )
    query = " ".join(
        str(issue.get(key, ""))
        for key in ("key", "summary", "description", "components", "labels", "qa_doc_refs")
    ) + " " + linked_qa_text + " " + qa_detail_text
    story_keys = set(extract_story_keys(query))
    query_tokens = tokenize(query)
    docs_by_id = {doc.get("id"): doc for doc in qa_index.get("documents", [])}
    refs = [str(item) for item in issue.get("qa_doc_refs") or []]
    explicit_docs = qa_documents_matching_refs(qa_index, refs)
    explicit_doc_ids = {doc.get("id") for doc in explicit_docs if doc.get("id")}
    has_explicit_qa_refs = bool(refs)
    if has_explicit_qa_refs and not explicit_doc_ids and not story_keys:
        return []
    by_story = qa_index.get("by_story") if isinstance(qa_index.get("by_story"), dict) else {}
    story_doc_ids: set[str] = set()
    story_case_ids: set[str] = set()
    for key in story_keys:
        entry = by_story.get(key) or by_story.get(str(key).upper()) or {}
        if not isinstance(entry, dict):
            continue
        story_doc_ids.update(str(doc_id) for doc_id in entry.get("doc_ids") or [] if str(doc_id))
        story_case_ids.update(str(case_id) for case_id in entry.get("case_ids") or [] if str(case_id))
    if explicit_doc_ids:
        candidate_cases = qa_cases_for_doc_ids(qa_index, {str(doc_id) for doc_id in explicit_doc_ids if doc_id})
    elif story_case_ids:
        case_by_id = qa_index.get("_case_by_id") if isinstance(qa_index.get("_case_by_id"), dict) else {}
        candidate_cases = [case_by_id[case_id] for case_id in story_case_ids if case_id in case_by_id]
    elif story_doc_ids:
        candidate_cases = qa_cases_for_doc_ids(qa_index, story_doc_ids)
    else:
        return []
    ranked: list[dict[str, Any]] = []
    for case in candidate_cases:
        if not isinstance(case, dict):
            continue
        score = 0.0
        source_bits: list[str] = []
        case_story_keys = set(case.get("story_keys") or [])
        if story_keys and story_keys & case_story_keys:
            score += 1.0
            source_bits.append("StoryKey")
        doc = docs_by_id.get(case.get("doc_id", ""), {})
        if explicit_doc_ids:
            if case.get("doc_id") not in explicit_doc_ids:
                continue
            score += 2.0
            source_bits.append("JiraQARef")
        elif refs and any(qa_ref_matches_document(ref, doc) for ref in refs):
            score += 1.0
            source_bits.append("JiraQARef")
        elif not story_keys and not qa_document_system_matches_issue(doc, query, evidence):
            continue
        case_tokens = set(case.get("tokens") or [])
        if query_tokens and case_tokens:
            overlap = query_tokens & case_tokens
            if overlap:
                score += min(0.35, len(overlap) / max(10, min(len(query_tokens), len(case_tokens))))
                source_bits.append("Text")
        affinity = 0.0
        if evidence:
            affinity = max(evidence_affinity_for_qa_case(case, item) for item in evidence)
            score += affinity
            if affinity >= 0.08:
                source_bits.append("DesignRef")
        if case.get("kind") == "Smoke":
            score += 0.06
        if qa_priority_sort_value(case) == 0:
            score += 0.04

        has_strong_link = "StoryKey" in source_bits or "JiraQARef" in source_bits
        if evidence and not has_strong_link and affinity < 0.12:
            continue
        min_score = 0.18 if has_strong_link else (0.28 if evidence else 0.34)
        if score < min_score:
            continue
        item = dict(case)
        item["qa_match_score"] = round(score, 4)
        item["qa_source"] = "+".join(dict.fromkeys(source_bits)) or "Weak"
        ranked.append(item)

    ranked.sort(
        key=lambda item: (
            float(item.get("qa_match_score", 0)),
            item.get("kind") == "Smoke",
            -qa_priority_sort_value(item),
            item.get("status") == "Open",
        ),
        reverse=True,
    )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ranked:
        case_id = str(item.get("id", ""))
        if case_id in seen:
            continue
        seen.add(case_id)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def summarize_qa_cases(cases: list[dict[str, Any]], compact: bool = True) -> str:
    if not cases:
        return "No QA"
    total = len(cases)
    done = sum(1 for case in cases if case.get("status") == "Done")
    open_count = total - done
    smoke = sum(1 for case in cases if case.get("kind") == "Smoke")
    if compact:
        if smoke:
            return f"{total} cases / {smoke} smoke"
        return f"{total} cases"
    return f"{total} cases, Done {done}, Open {open_count}, Smoke {smoke}"


def summarize_qa_method(cases: list[dict[str, Any]], limit: int = 1) -> str:
    if not cases:
        return ""

    def one_line(value: Any, max_len: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    chunks: list[str] = []
    for case in cases[:limit]:
        steps = " -> ".join(one_line(step, 60) for step in (case.get("operation_steps") or []) if str(step).strip())
        parts = [
            ("F", one_line(case.get("feature_point", ""), 50)),
            ("T", one_line(case.get("test_point", ""), 90)),
            ("Steps", one_line(steps, 110)),
            ("Expected", one_line(case.get("expected_result", ""), 90)),
        ]
        chunk = " | ".join(f"{label}: {value}" for label, value in parts if value)
        if chunk:
            chunks.append(chunk)
    if len(cases) > limit:
        chunks.append(f"+{len(cases) - limit} more")
    return " ; ".join(chunks)


def infer_feature_name(title: str, text: str) -> str:
    if title and len(title.strip()) > 1:
        return title.strip()[:80]
    first = re.split(r"[。\n.!?]", text.strip(), 1)[0]
    return first[:80] or "Audio candidate"


def infer_system(path: str, text: str) -> str:
    hay = f"{path}\n{text}".lower()
    mapping = [
        ("UI", ["ui", "\u754c\u9762", "\u6309\u94ae", "\u70b9\u51fb"]),
        ("Fishing", ["\u9c7c", "\u54ac\u94a9", "\u629b\u6295", "\u6536\u7ebf", "\u9c7c\u7aff"]),
        ("Environment", ["\u573a\u666f", "\u5929\u6c14", "\u96e8", "\u98ce", "\u9e1f", "\u751f\u7269"]),
        ("Items", ["\u9053\u5177", "\u88c5\u5907", "\u9493\u5177", "\u5546\u5e97"]),
        ("Progression", ["\u4efb\u52a1", "\u5956\u52b1", "\u6210\u5c31", "\u7ed3\u7b97"]),
    ]
    for name, words in mapping:
        if any(word in hay for word in words):
            return name
    return "Gameplay"


def load_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def save_index(index: dict[str, Any]) -> None:
    INDEX_PATH.write_text(json.dumps(serializable_index(index), ensure_ascii=False, indent=2), encoding="utf-8")


def serializable_index(index: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in index.items() if not str(key).startswith("_")}


def load_jira_issue_cache() -> dict[str, Any]:
    if not JIRA_CACHE_PATH.exists():
        return {}
    data = json.loads(JIRA_CACHE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    issues = data.get("issues")
    if not isinstance(issues, list):
        return {}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return {"metadata": metadata, "issues": issues}


def save_jira_issue_cache(
    issues: list[dict[str, Any]],
    *,
    jira_url: str,
    jql: str,
    source: str,
) -> dict[str, Any]:
    safe_issues = json.loads(json.dumps(issues, ensure_ascii=False, default=str))
    for issue in safe_issues:
        if isinstance(issue, dict):
            normalize_issue_match_state(issue)
    matched_count = sum(1 for issue in safe_issues if isinstance(issue, dict) and issue_has_persisted_match(issue))
    metadata = {
        "version": JIRA_CACHE_VERSION,
        "generated_at": now_stamp(),
        "jira_url": jira_url,
        "jql": jql,
        "source": source,
        "issue_count": len(safe_issues),
        "matched_count": matched_count,
        "unmatched_count": max(0, len(safe_issues) - matched_count),
        "note": "Local Jira cache only. Refresh manually when you need current status, assignee, links, or QA refs.",
    }
    payload = {
        "version": JIRA_CACHE_VERSION,
        "metadata": metadata,
        "issues": safe_issues,
    }
    JIRA_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def save_snapshot(index: dict[str, Any]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = SNAPSHOT_DIR / f"audio_requirement_index_{stamp}.json"
    path.write_text(json.dumps(serializable_index(index), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_snapshots() -> list[Path]:
    if not SNAPSHOT_DIR.exists():
        return []
    return sorted(SNAPSHOT_DIR.glob("audio_requirement_index_*.json"), key=lambda item: item.stat().st_mtime)


def requirement_signature(req: dict[str, Any]) -> str:
    evidence = clean_text(str(req.get("evidence", ""))).lower()
    evidence = re.sub(r"\s+", " ", evidence)[:500]
    base = f"{req.get('doc_path','')}|{req.get('locator','')}|{req.get('sound_type','')}|{evidence}"
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()


def compact_change_record(req: dict[str, Any], change_type: str) -> dict[str, Any]:
    return {
        "change_type": change_type,
        "id": req.get("id", ""),
        "doc_path": req.get("doc_path", ""),
        "full_path": req.get("full_path", ""),
        "title": req.get("title", ""),
        "locator": req.get("locator", ""),
        "feature": req.get("feature", ""),
        "system": req.get("system", ""),
        "sound_type": req.get("sound_type", ""),
        "sabc": req.get("sabc", ""),
        "ready_state": req.get("ready_state", ""),
        "audio_score": req.get("audio_score", 0),
        "reason": req.get("reason", ""),
        "evidence": req.get("evidence", ""),
        "local_ai": {},
    }


def diff_indexes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_docs = {doc["path"]: doc for doc in old.get("documents", [])}
    new_docs = {doc["path"]: doc for doc in new.get("documents", [])}
    added_docs = sorted(path for path in new_docs if path not in old_docs)
    removed_docs = sorted(path for path in old_docs if path not in new_docs)
    modified_docs = sorted(
        path
        for path, doc in new_docs.items()
        if path in old_docs and doc.get("sha1") != old_docs[path].get("sha1")
    )
    changed_doc_set = set(added_docs) | set(modified_docs)

    old_sigs = {requirement_signature(req) for req in old.get("requirements", [])}
    new_sigs = {requirement_signature(req) for req in new.get("requirements", [])}

    added_requirements = []
    for req in new.get("requirements", []):
        sig = requirement_signature(req)
        if sig not in old_sigs and req.get("doc_path") in changed_doc_set:
            added_requirements.append(compact_change_record(req, "NewAudioCandidate"))

    removed_requirements = []
    for req in old.get("requirements", []):
        sig = requirement_signature(req)
        if sig not in new_sigs and req.get("doc_path") in set(removed_docs) | set(modified_docs):
            removed_requirements.append(compact_change_record(req, "RemovedAudioCandidate"))

    def risk_key(item: dict[str, Any]) -> tuple[float, int]:
        sabc_weight = {"S": 4, "A": 3, "B": 2, "C": 1}.get(str(item.get("sabc", "C")), 0)
        return (float(item.get("audio_score", 0)), sabc_weight)

    added_requirements.sort(key=risk_key, reverse=True)
    likely_new_audio = [
        item
        for item in added_requirements
        if float(item.get("audio_score", 0)) >= 0.32
    ]
    impact_counts = Counter(item.get("sound_type", "Unknown") for item in likely_new_audio)
    ready_counts = Counter(item.get("ready_state", "Unknown") for item in likely_new_audio)
    diff = {
        "version": 1,
        "generated_at": now_stamp(),
        "old_generated_at": old.get("generated_at", ""),
        "new_generated_at": new.get("generated_at", ""),
        "design_root": new.get("design_root", ""),
        "summary": {
            "added_docs": len(added_docs),
            "removed_docs": len(removed_docs),
            "modified_docs": len(modified_docs),
            "new_audio_candidates": len(likely_new_audio),
            "removed_audio_candidates": len(removed_requirements),
            "impact_sound_types": dict(impact_counts),
            "ready_states": dict(ready_counts),
        },
        "added_docs": added_docs[:300],
        "removed_docs": removed_docs[:300],
        "modified_docs": modified_docs[:500],
        "new_audio_candidates": likely_new_audio[:1000],
        "removed_audio_candidates": removed_requirements[:300],
    }
    return diff


def write_diff_reports(diff: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = REPORT_DIR / f"ProjectEF_Design_AudioRequirement_Diff_{stamp}.json"
    md_path = REPORT_DIR / f"ProjectEF_Design_AudioRequirement_Diff_{stamp}.md"
    csv_path = REPORT_DIR / f"ProjectEF_Design_AudioRequirement_Diff_{stamp}.csv"
    prompt_path = REPORT_DIR / f"ProjectEF_Design_AudioRequirement_Diff_CodexReviewPrompt_{stamp}.md"
    json_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_DIFF_PATH.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = ["change_type", "sabc", "ready_state", "sound_type", "audio_score", "doc_path", "locator", "feature", "reason", "evidence"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in diff.get("new_audio_candidates", []):
            writer.writerow({key: item.get(key, "") for key in fields})

    lines = [
        "# ProjectEF Design Audio Requirement Diff",
        "",
        f"- Generated: {diff.get('generated_at','')}",
        f"- Old snapshot: {diff.get('old_generated_at','')}",
        f"- New snapshot: {diff.get('new_generated_at','')}",
        f"- Design root: `{diff.get('design_root','')}`",
        "",
        "## Summary",
        "",
    ]
    for key, value in diff.get("summary", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## New Audio Candidates",
        "",
        "| SABC | Ready | Type | Score | Source | Evidence |",
        "|---|---|---|---:|---|---|",
    ])
    for item in diff.get("new_audio_candidates", [])[:120]:
        source = f"{item.get('doc_path','')} {item.get('locator','')}"
        evidence = clean_text(item.get("evidence", "")).replace("\n", " ")[:240]
        lines.append(
            "| "
            + " | ".join(
                sanitize_md(str(value))
                for value in [
                    item.get("sabc", ""),
                    item.get("ready_state", ""),
                    item.get("sound_type", ""),
                    item.get("audio_score", ""),
                    source,
                    evidence,
                ]
            )
            + " |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    prompt_lines = [
        "# Codex Review Pack: ProjectEF Design Audio Requirement Diff",
        "",
        "Please review these newly changed design-document fragments and judge which ones create real audio work.",
        "Use conservative evidence rules: cite exact file paths and locators, mark weak evidence as Maybe/Unknown, and do not invent triggers.",
        "",
        "Return columns: AudioRequired, ReadyState, Source, Evidence, Why, Question.",
        "",
        "## Diff Summary",
        "```json",
        json.dumps(diff.get("summary", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Top Candidates",
    ]
    for index, item in enumerate(diff.get("new_audio_candidates", [])[:80], 1):
        prompt_lines.extend([
            "",
            f"### Candidate {index}",
            f"- Source: `{item.get('doc_path','')}` {item.get('locator','')}",
            f"- SABC: {item.get('sabc','')}  Ready: {item.get('ready_state','')}  Type: {item.get('sound_type','')}  Score: {item.get('audio_score','')}",
            f"- Rule reason: {item.get('reason','')}",
            "",
            clean_text(item.get("evidence", ""))[:1200],
        ])
    prompt_path.write_text("\n".join(prompt_lines), encoding="utf-8")
    return {
        "json": str(json_path),
        "md": str(md_path),
        "csv": str(csv_path),
        "codex_prompt": str(prompt_path),
        "latest": str(LATEST_DIFF_PATH),
    }


def default_config() -> dict[str, Any]:
    return {
        "design_root": str(DEFAULT_DESIGN_ROOT),
        "jira_url": DEFAULT_JIRA_URL,
        "jira_cookie": "",
        "jql": "assignee = yupeng AND statusCategory != Done ORDER BY updated DESC",
        "jql_limit": "500",
        "jira_qa_fields": [],
        "ollama_url": DEFAULT_OLLAMA_URL,
        "local_model": DEFAULT_LOCAL_MODEL,
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    if not CONFIG_PATH.exists():
        return config
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key not in config:
                    continue
                if key == "jira_qa_fields":
                    if isinstance(value, list):
                        config[key] = [str(item).strip() for item in value if str(item).strip()]
                    elif isinstance(value, str):
                        config[key] = [item.strip() for item in re.split(r"[,;\s]+", value) if item.strip()]
                else:
                    config[key] = str(value)
    except Exception:
        pass
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_design_index_lookup(index: dict[str, Any]) -> dict[str, list[tuple[str, int]]]:
    lookup = index.get("_token_lookup")
    if isinstance(lookup, dict):
        return lookup
    built: dict[str, list[tuple[str, int]]] = defaultdict(list)
    token_sets: dict[str, list[set[str]]] = {}
    for source_name in ("requirements", "chunks"):
        records = index.get(source_name, []) or []
        source_token_sets: list[set[str]] = []
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                source_token_sets.append(set())
                continue
            record_tokens = {str(token) for token in record.get("tokens") or [] if str(token)}
            source_token_sets.append(record_tokens)
            for token in record_tokens:
                if isinstance(token, str) and token:
                    built[token].append((source_name, record_index))
        token_sets[source_name] = source_token_sets
    index["_token_lookup"] = dict(built)
    index["_token_sets"] = token_sets
    return index["_token_lookup"]


def match_score(query_tokens: set[str], record: dict[str, Any]) -> float:
    tokens = set(record.get("tokens") or [])
    return match_score_with_tokens(query_tokens, record, tokens)


def match_score_with_tokens(query_tokens: set[str], record: dict[str, Any], tokens: set[str]) -> float:
    if not query_tokens or not tokens:
        return 0.0
    overlap = query_tokens & tokens
    if not overlap:
        return 0.0
    score = len(overlap) / max(4, len(query_tokens))
    score += min(0.35, float(record.get("audio_score", 0)) * 0.25)
    if record.get("ready_state") == "Ready":
        score += 0.04
    return round(score, 4)


def rank_evidence(issue: dict[str, Any], index: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    query = " ".join(str(issue.get(key, "")) for key in ("key", "summary", "description"))
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    lookup = ensure_design_index_lookup(index)
    token_sets_by_source = index.get("_token_sets") if isinstance(index.get("_token_sets"), dict) else {}
    token_counts = [
        (token, len(lookup.get(token, [])))
        for token in q_tokens
        if lookup.get(token)
    ]
    if not token_counts:
        return []
    chosen_tokens = [(token, count) for token, count in token_counts if count <= 2500]
    if not chosen_tokens:
        chosen_tokens = sorted(token_counts, key=lambda item: item[1])[:5]
    candidate_weights: dict[tuple[str, int], float] = defaultdict(float)
    for token, count in chosen_tokens:
        refs = lookup.get(token, [])
        weight = 1.0 / max(1.0, count ** 0.5)
        for ref in refs:
            candidate_weights[ref] += weight
    if len(candidate_weights) > 1400:
        candidate_refs = [
            ref
            for ref, _weight in sorted(candidate_weights.items(), key=lambda item: item[1], reverse=True)[:1400]
        ]
    else:
        candidate_refs = list(candidate_weights.keys())
    if not candidate_refs:
        return []
    scored_candidates: list[tuple[float, float, str, int]] = []
    for source_name, record_index in candidate_refs:
        records = index.get(source_name, []) or []
        if record_index < 0 or record_index >= len(records):
            continue
        record = records[record_index]
        if not isinstance(record, dict):
            continue
        source_token_sets = token_sets_by_source.get(source_name, []) if isinstance(token_sets_by_source, dict) else []
        record_tokens = source_token_sets[record_index] if record_index < len(source_token_sets) else set(record.get("tokens") or [])
        score = match_score_with_tokens(q_tokens, record, record_tokens)
        if score <= 0:
            continue
        scored_candidates.append((score, float(record.get("audio_score", 0) or 0), source_name, record_index))
    scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen = set()
    for score, _audio_score, source_name, record_index in scored_candidates:
        records = index.get(source_name, []) or []
        if record_index < 0 or record_index >= len(records):
            continue
        record = records[record_index]
        if not isinstance(record, dict):
            continue
        item = dict(record)
        item["match_score"] = score
        item["source"] = source_name
        key = (item.get("doc_path"), item.get("locator"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def classify_issue(issue: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(str(issue.get(key, "")) for key in ("summary", "description"))
    issue_audio_score, _, _, _, issue_reason = classify_audio_need(text, "")
    best = evidence[0] if evidence else {}
    best_score = float(best.get("match_score", 0))
    best_audio = float(best.get("audio_score", 0))
    specific_terms = specific_query_terms(text)
    best_text = " ".join(str(best.get(key, "")) for key in ("doc_path", "title", "locator", "evidence", "text"))
    best_tokens = tokenize(best_text)
    best_lower = best_text.lower()
    specific_overlap = {term for term in specific_terms if term.lower() in best_lower or term in best_tokens}
    if issue_audio_score >= 0.62 or (best_score >= 0.35 and best_audio >= 0.62):
        required = "Yes"
    elif issue_audio_score >= 0.32 or (best_score >= 0.2 and best_audio >= 0.32):
        required = "Maybe"
    elif evidence:
        required = "Unknown"
    else:
        required = "No"

    ready_states = [item.get("ready_state", "Unknown") for item in evidence[:5]]
    if required == "No":
        ready = "Cuttable"
    elif "Ready" in ready_states and required in {"Yes", "Maybe"}:
        ready = "Ready"
    elif "Risky" in ready_states:
        ready = "Risky"
    elif evidence:
        ready = "DesignOnly"
    else:
        ready = "UnknownNeedsDesign"

    if not evidence:
        reason = f"No matching design evidence found. Issue signal: {issue_reason}"
    else:
        reason = f"Best evidence score {best_score}; issue signal: {issue_reason}; evidence: {best.get('reason','')}"
    if evidence and specific_terms and not specific_overlap:
        if required == "Yes":
            required = "Maybe"
        if ready == "Ready":
            ready = "DesignOnly"
        reason += "; exact object terms were not found in the best evidence: " + ", ".join(sorted(specific_terms)[:8])
        confidence = "Low"
    else:
        confidence = confidence_label(issue_audio_score, best_score, best_audio)
    return {
        "audio_required": required,
        "ready_state": ready,
        "confidence": confidence,
        "reason": reason,
    }


def confidence_label(issue_audio_score: float, match: float, evidence_audio: float) -> str:
    combined = issue_audio_score * 0.45 + match * 0.35 + evidence_audio * 0.2
    if combined >= 0.55:
        return "High"
    if combined >= 0.28:
        return "Medium"
    return "Low"


def join_names(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, str):
        return values
    if isinstance(values, list):
        names = []
        for value in values:
            if isinstance(value, dict):
                names.append(str(value.get("name") or value.get("value") or "").strip())
            else:
                names.append(str(value).strip())
        return ", ".join(name for name in names if name)
    return str(values)


def split_multi_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = [str(item).strip() for item in value]
    else:
        raw = re.split(r"[,;|/]\s*|\s+->\s+", str(value))
    return [item for item in (part.strip() for part in raw) if item]


def dedupe_keep_order(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(str(value or ""))
        if not text:
            continue
        key = normalize_path(text).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def dedupe_refs_prefer_full_paths(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in dedupe_keep_order(values):
        norm = normalize_path(value).lower()
        if any(norm != normalize_path(existing).lower() and norm in normalize_path(existing).lower() for existing in result):
            continue
        result.append(value)
    return result


def issue_has_persisted_match(issue: dict[str, Any]) -> bool:
    if str(issue.get("match_status") or "").strip() == MATCH_STATUS_MATCHED:
        return True
    design_area = str(issue.get("design_area") or "").strip()
    return bool(issue.get("evidence")) or bool(issue.get("design_doc")) or design_area not in {
        "",
        NO_EVIDENCE_LABEL,
        UNMATCHED_DESIGN_LABEL,
    }


def normalize_issue_match_state(issue: dict[str, Any]) -> None:
    if not str(issue.get("match_status") or "").strip():
        issue["match_status"] = MATCH_STATUS_MATCHED if issue_has_persisted_match(issue) else MATCH_STATUS_NOT_MATCHED
    if (
        issue.get("match_status") == MATCH_STATUS_NOT_MATCHED
        and str(issue.get("design_area") or "").strip() in {"", NO_EVIDENCE_LABEL}
        and not issue.get("evidence")
        and not issue.get("design_doc")
    ):
        issue["design_area"] = UNMATCHED_DESIGN_LABEL


def jira_revision(issue: dict[str, Any]) -> str:
    return str(issue.get("updated") or "").strip()


def jira_match_input_signature(issue: dict[str, Any]) -> str:
    payload = {
        key: issue.get(key)
        for key in JIRA_MATCH_INPUT_FIELDS
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(clean_text(text).encode("utf-8", errors="ignore")).hexdigest()


def jira_issue_unchanged(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    old_revision = jira_revision(existing)
    new_revision = jira_revision(incoming)
    return bool(old_revision and new_revision and old_revision == new_revision)


def compact_jira_issue_record(issue: dict[str, Any], relation: str = "") -> dict[str, str]:
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    issue_type = fields.get("issuetype") if isinstance(fields.get("issuetype"), dict) else {}
    return {
        "key": str(issue.get("key") or "").strip(),
        "summary": str(fields.get("summary") or issue.get("summary") or "").strip(),
        "status": str(status.get("name") or "").strip(),
        "issue_type": str(issue_type.get("name") or "").strip(),
        "relation": relation,
    }


def linked_issue_records(values: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not isinstance(values, list):
        return records
    for link in values:
        if not isinstance(link, dict):
            continue
        link_type = ""
        if isinstance(link.get("type"), dict):
            link_type = str(link["type"].get("name") or link["type"].get("outward") or link["type"].get("inward") or "").strip()
        linked = link.get("outwardIssue") or link.get("inwardIssue")
        if isinstance(linked, dict):
            records.append(compact_jira_issue_record(linked, link_type))
    return records


def subtask_issue_records(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    return [compact_jira_issue_record(item, "Subtask") for item in values if isinstance(item, dict)]


def issue_link_labels(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    labels: list[str] = []
    for record in linked_issue_records(values):
        label = " ".join(part for part in (record.get("relation"), record.get("key"), record.get("status")) if part)
        if label:
            labels.append(label)
    return "; ".join(labels)


def all_related_jira_issue_records(fields: dict[str, Any]) -> list[dict[str, str]]:
    records = linked_issue_records(fields.get("issuelinks"))
    records.extend(subtask_issue_records(fields.get("subtasks")))
    parent = fields.get("parent")
    if isinstance(parent, dict):
        records.append(compact_jira_issue_record(parent, "Parent"))
    return [item for item in records if item.get("key")]


def looks_like_qa_design_issue(record: dict[str, Any]) -> bool:
    hay = clean_text(
        " ".join(
            str(record.get(key, ""))
            for key in ("key", "summary", "issue_type", "relation", "status")
        )
    ).lower()
    return any(hint.lower() in hay for hint in QA_DESIGN_ISSUE_HINTS)


def extract_qa_design_issue_refs(fields: dict[str, Any]) -> list[dict[str, str]]:
    return [record for record in all_related_jira_issue_records(fields) if looks_like_qa_design_issue(record)]


def issue_version_label(issue: dict[str, Any]) -> str:
    for key in ("fix_versions", "versions", "version"):
        value = str(issue.get(key, "")).strip()
        if value:
            return value
    text = " ".join(str(issue.get(key, "")) for key in ("summary", "description"))
    patterns = [
        r"(?:版本|版号|Version|ver\.?|V)\s*[:：]?\s*([A-Za-z0-9_.-]{2,24})",
        r"\bV\d+(?:\.\d+){0,3}\b",
        r"\b\d+\.\d+(?:\.\d+){0,2}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        return match.group(1) if match.lastindex else match.group(0)
    return "Unspecified"


def design_area_from_doc_path(doc_path: str) -> str:
    if not doc_path:
        return NO_EVIDENCE_LABEL
    parts = [part for part in re.split(r"[\\/]+", doc_path) if part]
    if not parts:
        return NO_EVIDENCE_LABEL
    anchors = {"策划文档", "功能文档", "表格文档", "系统文档"}
    for idx, part in enumerate(parts):
        if part in anchors and idx + 1 < len(parts):
            return "/".join(parts[idx + 1 : min(len(parts), idx + 4)])
    return "/".join(parts[: min(len(parts), 3)])


def can_start_label(issue: dict[str, Any]) -> str:
    required = issue.get("audio_required", "Unknown")
    ready = issue.get("ready_state", "Unknown")
    if required == "No" or ready == "Cuttable":
        return "NoAudio"
    if required in {"Yes", "Maybe"} and ready == "Ready":
        return "Ready"
    if ready == "DesignOnly":
        return "DesignOnly"
    if ready in {"Blocked", "UnknownNeedsDesign"}:
        return "Blocked"
    if ready == "Risky":
        return "Risky"
    return "Unknown"


def dependency_label(issue: dict[str, Any]) -> str:
    links = str(issue.get("issue_links", "")).strip()
    if links:
        return links
    ready = issue.get("ready_state", "Unknown")
    can_start = issue.get("can_start", "Unknown")
    if can_start == "Ready":
        return "NoBlockingDependency"
    if ready == "DesignOnly":
        return "NeedsDesignReview"
    if ready == "Risky":
        return "RiskyNeedsOwnerCheck"
    if ready in {"Blocked", "UnknownNeedsDesign"}:
        return "NeedsDesignEvidence"
    if ready == "Cuttable":
        return "NoAudioDependency"
    return "UnknownDependency"


def assign_issue_dimensions(issue: dict[str, Any]) -> None:
    evidence = issue.get("evidence") or []
    best = evidence[0] if evidence else {}
    issue["design_area"] = design_area_from_doc_path(best.get("doc_path", ""))
    issue["design_doc"] = best.get("doc_path", "")
    issue["system"] = best.get("system") or infer_system(best.get("doc_path", ""), f"{issue.get('summary','')}\n{issue.get('description','')}")
    issue["sound_type"] = best.get("sound_type", "")
    issue["version_label"] = issue_version_label(issue)
    issue["can_start"] = can_start_label(issue)
    issue["dependency_label"] = dependency_label(issue)


def jira_request(base_url: str, path: str, cookie: str = "", timeout: int = 15) -> tuple[int, str, str]:
    url = base_url.rstrip("/") + path
    headers = {"Accept": "application/json, text/html;q=0.9"}
    if cookie.strip():
        headers["Cookie"] = cookie.strip()
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("Content-Type", ""), body


def find_edge_executable() -> str:
    candidates = [
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise RuntimeError("Microsoft Edge was not found. Install Edge or add msedge.exe to PATH.")


def jira_issue_navigator_url(base_url: str, jql: str = "") -> str:
    base = (base_url or DEFAULT_JIRA_URL).strip().rstrip("/")
    if jql.strip():
        return base + "/issues/?jql=" + urllib.parse.quote(jql.strip(), safe="")
    return base + "/issues/"


def cdp_http_json(path: str, timeout: int = 3, method: str = "GET") -> Any:
    url = f"http://127.0.0.1:{JIRA_CDP_PORT}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    return json.loads(text)


def cdp_is_available() -> bool:
    try:
        cdp_http_json("/json/version", timeout=1)
        return True
    except Exception:
        return False


def start_dedicated_jira_browser(base_url: str, jql: str = "") -> None:
    url = jira_issue_navigator_url(base_url, jql)
    start_dedicated_jira_browser_url(url)


def start_dedicated_jira_browser_url(url: str) -> None:
    DEDICATED_JIRA_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    edge = find_edge_executable()
    args = [
        edge,
        f"--user-data-dir={DEDICATED_JIRA_PROFILE_DIR}",
        f"--remote-debugging-port={JIRA_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--no-proxy-server",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        url,
    ]
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def cdp_new_tab(url: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(url, safe=":/?&=%#")
    return cdp_http_json(f"/json/new?{encoded}", timeout=5, method="PUT")


def cdp_list_targets() -> list[dict[str, Any]]:
    data = cdp_http_json("/json/list", timeout=3)
    return data if isinstance(data, list) else []


def get_or_create_jira_cdp_target(base_url: str, jql: str = "") -> dict[str, Any]:
    parsed = urllib.parse.urlparse(base_url if "://" in base_url else "http://" + base_url)
    host = (parsed.hostname or "").lower()
    targets = cdp_list_targets()
    for target in targets:
        if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
            continue
        target_url = str(target.get("url", ""))
        target_host = (urllib.parse.urlparse(target_url).hostname or "").lower()
        if host and target_host == host:
            return target
    return cdp_new_tab(jira_issue_navigator_url(base_url, jql))


class CdpWebSocket:
    def __init__(self, ws_url: str, timeout: int = 30) -> None:
        self.ws_url = ws_url
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> "CdpWebSocket":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.ws_url)
        if parsed.scheme != "ws":
            raise RuntimeError(f"Unsupported CDP websocket scheme: {parsed.scheme}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        sock = socket.create_connection((host, port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("Could not connect to the dedicated Jira browser debug session.")
        self.sock = sock

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _recv_exact(self, count: int) -> bytes:
        if self.sock is None:
            raise RuntimeError("CDP websocket is not connected.")
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise RuntimeError("CDP websocket closed unexpectedly.")
            data += chunk
        return data

    def _send_frame(self, text: str, opcode: int = 0x1) -> None:
        if self.sock is None:
            raise RuntimeError("CDP websocket is not connected.")
        payload = text.encode("utf-8")
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _send_pong(self, payload: bytes) -> None:
        if self.sock is None:
            return
        header = bytearray([0x8A])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_frame(self) -> tuple[int, bool, bytes]:
        first, second = self._recv_exact(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, fin, payload

    def recv_message(self) -> str:
        chunks: list[bytes] = []
        while True:
            opcode, fin, payload = self._recv_frame()
            if opcode == 0x8:
                raise RuntimeError("CDP websocket was closed by the browser.")
            if opcode == 0x9:
                self._send_pong(payload)
                continue
            if opcode in (0x1, 0x0):
                chunks.append(payload)
                if fin:
                    return b"".join(chunks).decode("utf-8", errors="replace")

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: int | None = None) -> dict[str, Any]:
        if self.sock is None:
            raise RuntimeError("CDP websocket is not connected.")
        old_timeout = self.sock.gettimeout()
        if timeout is not None:
            self.sock.settimeout(timeout)
        call_id = self.next_id
        self.next_id += 1
        self._send_frame(json.dumps({"id": call_id, "method": method, "params": params or {}}, ensure_ascii=False))
        try:
            while True:
                raw = self.recv_message()
                data = json.loads(raw)
                if data.get("id") != call_id:
                    continue
                if "error" in data:
                    message = data["error"].get("message", data["error"])
                    raise RuntimeError(f"CDP {method} failed: {message}")
                return data.get("result", {})
        finally:
            if timeout is not None:
                self.sock.settimeout(old_timeout)


def cdp_fetch_jira_url(base_url: str, jql: str, path_with_query: str, timeout: int = 60) -> dict[str, Any]:
    target = get_or_create_jira_cdp_target(base_url, jql)
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("Dedicated Jira browser has no debuggable page target.")
    base = base_url.rstrip("/")
    fetch_url = base + path_with_query
    with CdpWebSocket(ws_url, timeout=timeout) as cdp:
        cdp.call("Page.enable")
        current = cdp.call(
            "Runtime.evaluate",
            {"expression": "location.href", "returnByValue": True},
            timeout=10,
        ).get("result", {}).get("value", "")
        current_host = (urllib.parse.urlparse(str(current)).hostname or "").lower()
        target_host = (urllib.parse.urlparse(base).hostname or "").lower()
        if current_host != target_host:
            cdp.call("Page.navigate", {"url": jira_issue_navigator_url(base_url, jql)}, timeout=10)
            time.sleep(2.0)
        expression = f"""
(async () => {{
  const response = await fetch({json.dumps(fetch_url)}, {{
    credentials: 'include',
    headers: {{ 'Accept': 'application/json, text/html;q=0.9' }}
  }});
  const text = await response.text();
  return {{
    status: response.status,
    contentType: response.headers.get('content-type') || '',
    finalUrl: response.url,
    pageUrl: location.href,
    title: document.title || '',
    text
  }};
}})()
"""
        result = cdp.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
            timeout=timeout,
        )
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError("Dedicated Jira browser returned an unreadable response.")
    return value


def chromium_user_data_roots() -> list[tuple[str, Path]]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    return [
        ("Chrome", local / "Google" / "Chrome" / "User Data"),
        ("Edge", local / "Microsoft" / "Edge" / "User Data"),
    ]


def chromium_profiles(user_data_root: Path) -> list[Path]:
    profiles: list[Path] = []
    for name in ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4", "Profile 5"):
        path = user_data_root / name
        if path.exists():
            profiles.append(path)
    if not profiles and user_data_root.exists():
        profiles = [path for path in user_data_root.iterdir() if path.is_dir() and (path / "Network" / "Cookies").exists()]
    return profiles


def chromium_master_key(user_data_root: Path) -> bytes | None:
    if win32crypt is None:
        return None
    local_state = user_data_root / "Local State"
    if not local_state.exists():
        return None
    try:
        data = json.loads(local_state.read_text(encoding="utf-8", errors="replace"))
        encrypted_key = base64.b64decode(data.get("os_crypt", {}).get("encrypted_key", ""))
        if encrypted_key.startswith(b"DPAPI"):
            encrypted_key = encrypted_key[5:]
        return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    except Exception:
        return None


def decrypt_chromium_cookie(encrypted_value: bytes, master_key: bytes | None) -> str:
    if not encrypted_value:
        return ""
    if encrypted_value.startswith((b"v10", b"v11", b"v20")) and master_key and AESGCM is not None:
        nonce = encrypted_value[3:15]
        payload = encrypted_value[15:]
        try:
            return AESGCM(master_key).decrypt(nonce, payload, None).decode("utf-8", errors="replace")
        except Exception:
            return ""
    if win32crypt is not None:
        try:
            return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode("utf-8", errors="replace")
        except Exception:
            return ""
    return ""


def host_matches_cookie_domain(host: str, cookie_domain: str) -> bool:
    host = host.lower().strip()
    domain = cookie_domain.lower().strip().lstrip(".")
    return bool(domain and (host == domain or host.endswith("." + domain)))


def import_browser_jira_cookie_header(jira_url: str) -> tuple[str, str, int]:
    parsed = urllib.parse.urlparse(jira_url if "://" in jira_url else "http://" + jira_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise RuntimeError("Jira URL has no host.")
    domain_tokens = sorted({host, ".".join(host.split(".")[-2:]), ".".join(host.split(".")[-3:])})
    cookies: dict[str, tuple[str, str]] = {}
    sources: list[str] = []
    errors: list[str] = []

    for browser_name, user_data_root in chromium_user_data_roots():
        if not user_data_root.exists():
            continue
        master_key = chromium_master_key(user_data_root)
        for profile in chromium_profiles(user_data_root):
            cookie_paths = [profile / "Network" / "Cookies", profile / "Cookies"]
            for cookie_db in cookie_paths:
                if not cookie_db.exists():
                    continue
                temp_db = APP_DIR / f"_tmp_{browser_name}_{profile.name}_cookies.sqlite"
                connection = None
                try:
                    try:
                        shutil.copy2(cookie_db, temp_db)
                        connection = sqlite3.connect(temp_db)
                    except Exception:
                        uri = cookie_db.resolve().as_posix().replace("'", "''")
                        connection = sqlite3.connect(f"file:{uri}?mode=ro&immutable=1", uri=True)
                    connection.row_factory = sqlite3.Row
                    token_filters = [f"%{token}%" for token in domain_tokens if token]
                    clauses = " OR ".join(["host_key LIKE ?"] * len(token_filters))
                    query = "SELECT host_key, name, value, encrypted_value FROM cookies"
                    if clauses:
                        query += " WHERE " + clauses
                    for row in connection.execute(query, token_filters):
                        host_key = str(row["host_key"] or "")
                        if not host_matches_cookie_domain(host, host_key):
                            continue
                        name = str(row["name"] or "").strip()
                        if not name:
                            continue
                        value = str(row["value"] or "")
                        if not value:
                            value = decrypt_chromium_cookie(row["encrypted_value"], master_key)
                        if not value:
                            continue
                        cookies[name] = (value, host_key)
                        sources.append(f"{browser_name}/{profile.name}")
                except Exception:
                    errors.append(f"{browser_name}/{profile.name}: unable to read {cookie_db.name}")
                    continue
                finally:
                    try:
                        if connection is not None:
                            connection.close()
                    except Exception:
                        pass
                    try:
                        temp_db.unlink(missing_ok=True)
                    except Exception:
                        pass

    if not cookies:
        running = edge_or_chrome_running()
        details = "No Jira cookies found in Chrome/Edge profiles."
        if errors:
            details += "\n\nCookie database read errors:\n" + "\n".join(errors[:6])
        if running:
            details += "\n\nChrome/Edge is currently running, so the Cookie database may be locked. Close all Edge/Chrome windows, make sure no msedge.exe remains, then click Use Browser Login again."
        return "", details, 0
    header = "; ".join(f"{name}={value}" for name, (value, _domain) in sorted(cookies.items()))
    source_label = ", ".join(sorted(set(sources))) or "browser profile"
    return header, source_label, len(cookies)


def edge_or_chrome_running() -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for image_name in ("msedge.exe", "chrome.exe"):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=flags,
            )
            if image_name in result.stdout.lower():
                return True
        except Exception:
            continue
    return False


def parse_issue_from_json(data: dict[str, Any]) -> dict[str, Any]:
    fields = data.get("fields") or {}
    description = fields.get("description") or ""
    if isinstance(description, dict):
        description = json.dumps(description, ensure_ascii=False)
    qa_design_issues = extract_qa_design_issue_refs(fields)
    return {
        "key": data.get("key", ""),
        "summary": fields.get("summary", ""),
        "description": strip_html(str(description)),
        "status": ((fields.get("status") or {}).get("name") if isinstance(fields.get("status"), dict) else ""),
        "assignee": ((fields.get("assignee") or {}).get("displayName") if isinstance(fields.get("assignee"), dict) else ""),
        "reporter": ((fields.get("reporter") or {}).get("displayName") if isinstance(fields.get("reporter"), dict) else ""),
        "creator": ((fields.get("creator") or {}).get("displayName") if isinstance(fields.get("creator"), dict) else ""),
        "updated": fields.get("updated", ""),
        "project": ((fields.get("project") or {}).get("key") if isinstance(fields.get("project"), dict) else ""),
        "issue_type": ((fields.get("issuetype") or {}).get("name") if isinstance(fields.get("issuetype"), dict) else ""),
        "priority": ((fields.get("priority") or {}).get("name") if isinstance(fields.get("priority"), dict) else ""),
        "components": join_names(fields.get("components")),
        "labels": join_names(fields.get("labels")),
        "issue_links": issue_link_labels(fields.get("issuelinks")),
        "fix_versions": join_names(fields.get("fixVersions")),
        "versions": join_names(fields.get("versions")),
        "qa_doc_refs": extract_jira_qa_refs(fields),
        "qa_design_issues": qa_design_issues,
        "source": "Jira REST",
        "url": "",
    }


def parse_issue_from_html(body: str, key: str = "") -> dict[str, Any]:
    title = ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(body, "html.parser")
        title_node = soup.find("title")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        summary_node = soup.find(id="summary-val") or soup.find(attrs={"data-testid": re.compile("summary", re.I)})
        desc_node = soup.find(id="description-val") or soup.find(id="descriptionmodule")
        summary = summary_node.get_text(" ", strip=True) if summary_node else title
        description = desc_node.get_text("\n", strip=True) if desc_node else soup.get_text("\n", strip=True)[:6000]
    else:
        if re.search(r"<title>(.*?)</title>", body, re.I | re.S):
            title = re.search(r"<title>(.*?)</title>", body, re.I | re.S).group(1)
        summary = strip_html(title)
        description = strip_html(body)[:6000]
    return {
        "key": key,
        "summary": summary,
        "description": description,
        "status": "",
        "assignee": "",
        "updated": "",
        "qa_doc_refs": split_possible_jira_qa_refs(description),
        "source": "Jira HTML",
        "url": "",
    }


def is_jira_login_page(body: str, title: str = "") -> bool:
    hay = f"{title}\n{body[:5000]}".lower()
    return (
        "\u767b\u5f55" in title
        or "\u767b\u9304" in title
        or "\u767b\u9646" in title
        or "login" in hay
        or "login.jsp" in hay
        or "os_username" in hay
        or "atl_token" in hay and "jira" in hay and "password" in hay
    )


def issue_from_manual_text(key: str, text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = lines[0] if lines else key or "Manual Jira text"
    return {
        "key": key.strip(),
        "summary": summary,
        "description": text.strip(),
        "status": "",
        "assignee": "",
        "updated": "",
        "qa_doc_refs": split_possible_jira_qa_refs(text),
        "source": "Manual text",
        "url": "",
    }


def csv_value(row: dict[str, str], names: list[str]) -> str:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return str(value).strip()
    for key, value in row.items():
        normalized = str(key).strip().lower().replace(" ", "").replace("_", "").replace("/", "")
        for name in names:
            if normalized == name.lower().replace(" ", "").replace("_", "").replace("/", "") and value:
                return str(value).strip()
    return ""


def parse_issue_from_csv_row(row: dict[str, str], fallback_index: int) -> dict[str, Any]:
    key = csv_value(row, ["Issue key", "Key", "Issue Key", "问题键", "问题关键字", "编号", "键"])
    summary = csv_value(row, ["Summary", "摘要", "概要", "标题"])
    description = csv_value(row, ["Description", "描述", "说明"])
    status = csv_value(row, ["Status", "状态"])
    assignee = csv_value(row, ["Assignee", "经办人", "负责人", "处理人"])
    reporter = csv_value(row, ["Reporter", "报告人", "发起人", "提出人"])
    creator = csv_value(row, ["Creator", "创建人", "创建者"])
    updated = csv_value(row, ["Updated", "更新日期", "已更新", "更新时间"])
    if not key:
        key = f"CSV-{fallback_index}"
    if not summary:
        summary = description.splitlines()[0][:120] if description else key
    return {
        "key": key,
        "summary": summary,
        "description": description,
        "status": status,
        "assignee": assignee,
        "reporter": reporter,
        "creator": creator,
        "updated": updated,
        "project": csv_value(row, ["Project key", "Project", "项目"]),
        "issue_type": csv_value(row, ["Issue Type", "Issue type", "类型", "问题类型"]),
        "priority": csv_value(row, ["Priority", "优先级"]),
        "components": csv_value(row, ["Component/s", "Components", "组件", "模块"]),
        "labels": csv_value(row, ["Labels", "标签"]),
        "issue_links": csv_value(row, ["Linked Issues", "Issue Links", "Issue links", "关联问题", "链接问题"]),
        "fix_versions": csv_value(row, ["Fix Version/s", "Fix versions", "Fix Version", "修复版本", "目标版本"]),
        "versions": csv_value(row, ["Affects Version/s", "Affects versions", "Affects Version", "影响版本", "版本"]),
        "qa_doc_refs": split_possible_jira_qa_refs(
            " ".join(
                csv_value(row, names)
                for names in (
                    ["QA", "Smoke", "Test Case", "Checklist", "冒烟测试", "测试用例", "验收文档"],
                    ["QA Path", "QA File", "QA Doc", "QA Document", "Test Case Design", "Test Case Path", "Acceptance Checklist"],
                    ["测试用例设计", "测试用例位置", "用例设计", "用例位置", "验收用例", "验收文档"],
                    ["Description", "描述", "说明"],
                )
            )
        ),
        "source": "Jira CSV",
        "url": "",
    }


def extract_jql_from_jira_url(text: str) -> tuple[str, str]:
    value = (text or "").strip()
    if not value:
        return "", ""
    parsed = urllib.parse.urlparse(value)
    params = urllib.parse.parse_qs(parsed.query)
    jql_values = params.get("jql") or params.get("JQL")
    jql = jql_values[0].strip() if jql_values else ""
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    return jql, base_url


class TriageGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ProjectEF Audio Requirement Jira Triage")
        self.geometry("1680x960")
        self.minsize(1280, 760)
        self.configure(bg=BG)

        config = load_config()
        self.design_root_var = tk.StringVar(value=config["design_root"])
        self.jira_url_var = tk.StringVar(value=config["jira_url"])
        self.jira_cookie_var = tk.StringVar(value=config["jira_cookie"])
        self.jql_var = tk.StringVar(value=config["jql"])
        self.jql_limit_var = tk.StringVar(value=config.get("jql_limit", "500"))
        self.jira_qa_fields: list[str] = list(config.get("jira_qa_fields") or [])
        self.issue_key_var = tk.StringVar(value="PROEF-9209")
        self.ollama_url_var = tk.StringVar(value=config["ollama_url"])
        self.local_model_var = tk.StringVar(value=config["local_model"])
        self.model_mode_var = tk.StringVar(value="Rules")
        self.local_diff_limit_var = tk.StringVar(value="20")
        self.search_var = tk.StringVar()
        self.filter_system_var = tk.StringVar(value="All")
        self.filter_version_var = tk.StringVar(value="All")
        self.filter_start_var = tk.StringVar(value="All")
        self.filter_audio_var = tk.StringVar(value="All")
        self.filter_ready_var = tk.StringVar(value="All")
        self.filter_status_var = tk.StringVar(value="All")
        self.filter_type_var = tk.StringVar(value="All")
        self.filter_assignee_var = tk.StringVar(value="All")
        self.filter_reporter_var = tk.StringVar(value="All")
        self.filter_creator_var = tk.StringVar(value="All")
        self.filter_priority_var = tk.StringVar(value="All")
        self.filter_design_area_var = tk.StringVar(value="All")
        self.filter_design_doc_var = tk.StringVar(value="All")
        self.filter_dependency_var = tk.StringVar(value="All")
        self.filter_component_var = tk.StringVar(value="All")
        self.filter_label_var = tk.StringVar(value="All")
        self.status_var = tk.StringVar(value="Ready. Scan Design or Load Index first.")
        self.summary_var = tk.StringVar(value="")
        self.selected_summary_var = tk.StringVar(value="Select a Jira issue to view matched design evidence.")
        self.qa_path_var = tk.StringVar(value="QA Path: -")
        self.detail_visible_var = tk.BooleanVar(value=False)

        self.index: dict[str, Any] = {}
        self.qa_index: dict[str, Any] = {}
        self.latest_diff: dict[str, Any] = {}
        self.issues: list[dict[str, Any]] = []
        self.jira_cache_meta: dict[str, Any] = {}
        self.jira_issue_detail_cache: dict[str, dict[str, Any]] = {}
        self.matching_issues = False
        self.match_index = 0
        self.match_after_complete = None
        self.scan_cancel_requested = False
        self.visible_issue_iids: list[str] = []
        self.system_filter_combo: ttk.Combobox | None = None
        self.version_filter_combo: ttk.Combobox | None = None
        self.start_filter_combo: ttk.Combobox | None = None
        self.filter_combos: dict[str, ttk.Combobox] = {}
        self.detail_frame: tk.Frame | None = None
        self.evidence_frame: tk.Frame | None = None
        self.detail_toggle_button: tk.Button | None = None

        self.configure_style()
        self.build_ui()
        self.try_load_index_silent()
        self.try_load_qa_index_silent()
        self.try_load_jira_cache_silent()

    def configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=25, background="#101720", foreground=INK, fieldbackground="#101720")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#315577")], foreground=[("selected", "#ffffff")])
        style.configure("TCombobox", fieldbackground=PANEL_2, foreground=INK)

    def panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)

    def button(self, parent: tk.Misc, text: str, command, bg: str = CARD) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=INK,
            activebackground="#2a3c55",
            activeforeground=INK,
            relief=tk.FLAT,
            padx=12,
            pady=6,
            font=("Segoe UI", 9, "bold"),
        )

    def entry(self, parent: tk.Misc, label: str, var: tk.StringVar, width_px: int, show: str = "") -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL)
        tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Entry(
            frame,
            textvariable=var,
            bg=PANEL_2,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            width=max(4, width_px // 8),
            show=show,
        ).pack(anchor="w", ipady=4)
        return frame

    def add_filter_combo(self, parent: tk.Misc, row: int, column: int, label: str, var: tk.StringVar, width: int = 14) -> ttk.Combobox:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).grid(
            row=row,
            column=column * 2,
            sticky="e",
            padx=(8, 4),
            pady=4,
        )
        combo = ttk.Combobox(parent, textvariable=var, values=["All"], width=width, state="readonly")
        combo.grid(row=row, column=column * 2 + 1, sticky="w", padx=(0, 8), pady=4)
        combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_issue_table())
        self.filter_combos[label] = combo
        return combo

    def build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill=tk.X, padx=16, pady=(12, 8))
        tk.Label(header, text="ProjectEF Audio Requirement Jira Triage", bg=BG, fg=INK, font=("Segoe UI", 20, "bold")).pack(side=tk.LEFT)
        tk.Label(header, textvariable=self.summary_var, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side=tk.RIGHT)

        design_panel = self.panel(self)
        design_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.entry(design_panel, "Design Root", self.design_root_var, 520).pack(side=tk.LEFT, padx=(10, 8), pady=10)
        self.button(design_panel, "Browse", self.browse_design_root).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Scan Design", self.scan_design_async, bg="#2f6f5e").pack(side=tk.LEFT, padx=8)
        self.button(design_panel, "Scan QA", self.scan_qa_async, bg="#2f6f5e").pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Scan + Diff Changes", self.scan_diff_async, bg="#8867d8").pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Cancel Scan", self.cancel_scan_clicked, bg="#6b3440").pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Compare Latest", self.compare_latest_snapshots).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Load Index", self.load_index_clicked).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open Diff", self.open_latest_diff).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open Index", lambda: os.startfile(str(INDEX_PATH)) if INDEX_PATH.exists() else None).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open QA Index", lambda: os.startfile(str(QA_INDEX_PATH)) if QA_INDEX_PATH.exists() else None).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open Reports", lambda: os.startfile(str(REPORT_DIR))).pack(side=tk.LEFT, padx=4)

        jira_panel = self.panel(self)
        jira_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.entry(jira_panel, "Jira URL", self.jira_url_var, 300).pack(side=tk.LEFT, padx=(10, 8), pady=10)
        self.entry(jira_panel, "Cookie optional", self.jira_cookie_var, 300, show="*").pack(side=tk.LEFT, padx=8, pady=10)
        self.entry(jira_panel, "Issue Key", self.issue_key_var, 120).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(jira_panel, "Test Jira", self.test_jira).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Open Dedicated Jira", self.open_dedicated_jira_browser_clicked, bg="#315577").pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Restart Dedicated Jira", self.restart_dedicated_jira_browser_clicked, bg="#315577").pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Use Browser Login", self.use_browser_login_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Close Edge + Login", self.close_edge_then_login_clicked, bg="#8d5f32").pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Detect QA Fields", self.detect_jira_qa_fields_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Sync Issue", self.sync_issue_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Import Jira CSV", self.import_jira_csv_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Paste Jira Text", self.paste_jira_text).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Load Jira Cache", self.load_jira_cache_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Open Jira Cache", lambda: os.startfile(str(JIRA_CACHE_PATH)) if JIRA_CACHE_PATH.exists() else None).pack(side=tk.LEFT, padx=4)

        jql_panel = self.panel(self)
        jql_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.entry(jql_panel, "JQL", self.jql_var, 800).pack(side=tk.LEFT, padx=(10, 8), pady=10)
        self.button(jql_panel, "Use Jira URL", self.use_jira_url_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jql_panel, "One Click Refresh Jira", self.one_click_refresh_jira_clicked, bg="#2f6f5e").pack(side=tk.LEFT, padx=4)
        self.button(jql_panel, "Sync JQL", self.sync_jql_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jql_panel, "How To Use", self.show_quick_start).pack(side=tk.LEFT, padx=4)
        self.entry(jql_panel, "Limit", self.jql_limit_var, 70).pack(side=tk.LEFT, padx=8, pady=10)
        self.entry(jql_panel, "Ollama URL", self.ollama_url_var, 220).pack(side=tk.LEFT, padx=8, pady=10)
        self.entry(jql_panel, "Local Model", self.local_model_var, 190).pack(side=tk.LEFT, padx=8, pady=10)
        ttk.Combobox(jql_panel, textvariable=self.model_mode_var, values=["Rules", "Local Ollama", "Hybrid", "Codex Pack"], width=14, state="readonly").pack(side=tk.LEFT, padx=8)
        self.entry(jql_panel, "Diff AI Limit", self.local_diff_limit_var, 80).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(jql_panel, "Test Local AI", self.test_local_ai).pack(side=tk.LEFT, padx=4)
        self.button(jql_panel, "Local AI Selected", self.local_ai_selected).pack(side=tk.LEFT, padx=4)
        self.button(jql_panel, "Local AI Diff", self.local_ai_diff_clicked).pack(side=tk.LEFT, padx=4)

        toolbar = self.panel(self)
        toolbar.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(toolbar, text="Search", bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 6))
        search = tk.Entry(toolbar, textvariable=self.search_var, bg=PANEL_2, fg=INK, insertbackground=INK, relief=tk.FLAT, width=46)
        search.pack(side=tk.LEFT, padx=(0, 12), pady=10, ipady=5)
        search.bind("<KeyRelease>", lambda _event: self.refresh_issue_table())
        self.button(toolbar, "Clear Filters", self.clear_filters).pack(side=tk.LEFT, padx=4)
        self.button(toolbar, "Match All Issues", self.match_all_issues, bg="#2f6f5e").pack(side=tk.LEFT, padx=4)
        self.button(toolbar, "Open Evidence File", self.open_selected_evidence).pack(side=tk.LEFT, padx=4)
        self.button(toolbar, "Show QA Cases", self.show_selected_qa_cases).pack(side=tk.LEFT, padx=4)
        self.button(toolbar, "Open QA Path", self.open_selected_qa_file).pack(side=tk.LEFT, padx=4)
        self.button(toolbar, "Copy Jira Reply Draft", self.copy_jira_reply).pack(side=tk.LEFT, padx=4)
        self.button(toolbar, "Export Report", self.export_report).pack(side=tk.LEFT, padx=4)

        filter_panel = self.panel(self)
        filter_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        filter_grid = tk.Frame(filter_panel, bg=PANEL)
        filter_grid.pack(anchor="w", padx=8, pady=8)
        self.system_filter_combo = self.add_filter_combo(filter_grid, 0, 0, "System", self.filter_system_var, 13)
        self.version_filter_combo = self.add_filter_combo(filter_grid, 0, 1, "Version", self.filter_version_var, 14)
        self.add_filter_combo(filter_grid, 0, 2, "Status", self.filter_status_var, 12)
        self.start_filter_combo = self.add_filter_combo(filter_grid, 0, 3, "Start", self.filter_start_var, 13)
        self.add_filter_combo(filter_grid, 0, 4, "Audio", self.filter_audio_var, 10)
        self.add_filter_combo(filter_grid, 0, 5, "Ready", self.filter_ready_var, 14)
        self.add_filter_combo(filter_grid, 0, 6, "Type", self.filter_type_var, 14)
        self.add_filter_combo(filter_grid, 1, 0, "Reporter", self.filter_reporter_var, 16)
        self.add_filter_combo(filter_grid, 1, 1, "Creator", self.filter_creator_var, 16)
        self.add_filter_combo(filter_grid, 1, 2, "Assignee", self.filter_assignee_var, 16)
        self.add_filter_combo(filter_grid, 1, 3, "Priority", self.filter_priority_var, 12)
        self.add_filter_combo(filter_grid, 1, 4, "Component", self.filter_component_var, 18)
        self.add_filter_combo(filter_grid, 1, 5, "Label", self.filter_label_var, 18)
        self.add_filter_combo(filter_grid, 2, 0, "Design Area", self.filter_design_area_var, 22)
        self.add_filter_combo(filter_grid, 2, 1, "Design Doc", self.filter_design_doc_var, 34)
        self.add_filter_combo(filter_grid, 2, 2, "Dependency", self.filter_dependency_var, 28)

        paned = tk.PanedWindow(self, orient=tk.VERTICAL, bg=BG, sashwidth=6)
        paned.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        top = tk.Frame(paned, bg=BG)
        paned.add(top, minsize=260, height=380)
        columns = ("key", "required", "start", "ready", "system", "version", "design", "dependency", "qa_status", "qa_path", "confidence", "status", "summary", "evidence")
        self.issue_tree = ttk.Treeview(top, columns=columns, show="headings", selectmode="extended")
        headings = {
            "key": "Jira",
            "required": "Audio?",
            "start": "Start?",
            "ready": "Ready",
            "system": "System",
            "version": "Version",
            "design": "Design",
            "dependency": "Dependency",
            "qa_status": "QA Link",
            "qa_path": "QA Path",
            "confidence": "Conf",
            "status": "Status",
            "summary": "Summary",
            "evidence": "Best Evidence",
        }
        widths = {
            "key": 105,
            "required": 75,
            "start": 95,
            "ready": 120,
            "system": 105,
            "version": 110,
            "design": 170,
            "dependency": 180,
            "qa_status": 125,
            "qa_path": 310,
            "confidence": 65,
            "status": 90,
            "summary": 280,
            "evidence": 320,
        }
        for col in columns:
            self.issue_tree.heading(col, text=headings[col])
            self.issue_tree.column(col, width=widths[col], anchor=tk.W)
        issue_y = ttk.Scrollbar(top, orient=tk.VERTICAL, command=self.issue_tree.yview)
        issue_x = ttk.Scrollbar(top, orient=tk.HORIZONTAL, command=self.issue_tree.xview)
        self.issue_tree.grid(row=0, column=0, sticky="nsew")
        issue_y.grid(row=0, column=1, sticky="ns")
        issue_x.grid(row=1, column=0, sticky="ew")
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)
        self.issue_tree.configure(yscrollcommand=issue_y.set, xscrollcommand=issue_x.set)
        self.issue_tree.bind("<<TreeviewSelect>>", lambda _event: self.on_issue_selected())
        self.issue_tree.bind("<Double-1>", lambda _event: self.open_selected_jira_issue())

        bottom = tk.Frame(paned, bg=BG)
        paned.add(bottom, minsize=220, height=300)
        bottom_header = tk.Frame(bottom, bg=BG)
        bottom_header.pack(fill=tk.X, pady=(0, 6))
        tk.Label(bottom_header, textvariable=self.selected_summary_var, bg=BG, fg=MUTED, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.detail_toggle_button = self.button(bottom_header, "Show Details", self.toggle_detail_panel)
        self.detail_toggle_button.pack(side=tk.RIGHT, padx=(8, 0))

        qa_path_header = tk.Frame(bottom, bg=BG)
        qa_path_header.pack(fill=tk.X, pady=(0, 6))
        tk.Label(qa_path_header, textvariable=self.qa_path_var, bg=BG, fg="#8bd6ca", anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.button(qa_path_header, "Open QA Path", self.open_selected_qa_file, bg="#315577").pack(side=tk.RIGHT, padx=(8, 0))

        self.detail_frame = tk.Frame(bottom, bg=BG)
        self.detail_text = tk.Text(self.detail_frame, height=7, bg="#101720", fg=INK, insertbackground=INK, relief=tk.FLAT, wrap=tk.WORD)
        detail_y = ttk.Scrollbar(self.detail_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_y.grid(row=0, column=1, sticky="ns")
        self.detail_frame.rowconfigure(0, weight=1)
        self.detail_frame.columnconfigure(0, weight=1)
        self.detail_text.configure(yscrollcommand=detail_y.set)
        self.detail_text.configure(state=tk.DISABLED)

        ev_columns = ("score", "audio", "ready", "type", "qa", "qa_method", "qa_source", "path", "locator")
        self.evidence_frame = tk.Frame(bottom, bg=BG)
        self.evidence_frame.pack(fill=tk.BOTH, expand=True)
        self.evidence_tree = ttk.Treeview(self.evidence_frame, columns=ev_columns, show="headings", selectmode="browse")
        ev_headings = {"score": "Match", "audio": "Audio", "ready": "Ready", "type": "Type", "qa": "QA Cases", "qa_method": "QA Method", "qa_source": "QA Source", "path": "Doc", "locator": "Where"}
        ev_widths = {"score": 70, "audio": 70, "ready": 110, "type": 110, "qa": 140, "qa_method": 560, "qa_source": 130, "path": 420, "locator": 170}
        for col in ev_columns:
            self.evidence_tree.heading(col, text=ev_headings[col])
            self.evidence_tree.column(col, width=ev_widths[col], anchor=tk.W)
        evidence_y = ttk.Scrollbar(self.evidence_frame, orient=tk.VERTICAL, command=self.evidence_tree.yview)
        evidence_x = ttk.Scrollbar(self.evidence_frame, orient=tk.HORIZONTAL, command=self.evidence_tree.xview)
        self.evidence_tree.grid(row=0, column=0, sticky="nsew")
        evidence_y.grid(row=0, column=1, sticky="ns")
        evidence_x.grid(row=1, column=0, sticky="ew")
        self.evidence_frame.rowconfigure(0, weight=1)
        self.evidence_frame.columnconfigure(0, weight=1)
        self.evidence_tree.configure(yscrollcommand=evidence_y.set, xscrollcommand=evidence_x.set)
        self.evidence_tree.bind("<Double-1>", lambda _event: self.open_selected_evidence())
        self.evidence_tree.bind("<<TreeviewSelect>>", lambda _event: self.update_selected_qa_path_label())

        manual_panel = self.panel(self)
        manual_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(manual_panel, text="Manual Jira text / notes", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        self.manual_text = tk.Text(manual_panel, height=4, bg="#101720", fg=INK, insertbackground=INK, relief=tk.FLAT, wrap=tk.WORD)
        self.manual_text.pack(fill=tk.X, padx=10, pady=(4, 10))

        status = tk.Label(self, textvariable=self.status_var, bg=BG, fg=MUTED, anchor="w")
        status.pack(fill=tk.X, padx=16, pady=(0, 8))

    def toggle_detail_panel(self) -> None:
        if self.detail_frame is None:
            return
        if self.detail_visible_var.get():
            self.detail_frame.pack_forget()
            self.detail_visible_var.set(False)
            if self.detail_toggle_button is not None:
                self.detail_toggle_button.configure(text="Show Details")
            return
        pack_options = {"fill": tk.X, "pady": (0, 6)}
        if self.evidence_frame is not None:
            pack_options["before"] = self.evidence_frame
        self.detail_frame.pack(**pack_options)
        self.detail_visible_var.set(True)
        if self.detail_toggle_button is not None:
            self.detail_toggle_button.configure(text="Hide Details")

    def browse_design_root(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.design_root_var.get() or str(DEFAULT_DESIGN_ROOT), parent=self)
        if selected:
            self.design_root_var.set(selected)
            self.save_current_config()

    def save_current_config(self) -> None:
        save_config({
            "design_root": self.design_root_var.get().strip(),
            "jira_url": self.jira_url_var.get().strip(),
            "jira_cookie": "",
            "jql": self.jql_var.get().strip(),
            "jql_limit": self.jql_limit_var.get().strip(),
            "jira_qa_fields": self.jira_qa_fields,
            "ollama_url": self.ollama_url_var.get().strip(),
            "local_model": self.local_model_var.get().strip(),
        })

    def jira_fields_param(self) -> str:
        fields = [item.strip() for item in JIRA_SEARCH_FIELDS.split(",") if item.strip()]
        for field_id in self.jira_qa_fields:
            field_id = str(field_id).strip()
            if field_id and field_id not in fields:
                fields.append(field_id)
        return ",".join(fields)

    def fetch_issue_json_detail_for_qa(self, key: str) -> dict[str, Any]:
        key = key.strip().upper()
        if not key:
            return {}
        if key in self.jira_issue_detail_cache:
            return self.jira_issue_detail_cache[key]
        base = self.jira_url_var.get().strip() or DEFAULT_JIRA_URL
        fields = urllib.parse.quote(self.jira_fields_param(), safe=",")
        if self.jira_cookie_var.get().strip():
            status, ctype, body = jira_request(
                base,
                f"/rest/api/2/issue/{urllib.parse.quote(key)}?fields={fields}",
                self.jira_cookie_var.get().strip(),
                timeout=15,
            )
            if status != 200 or "json" not in ctype.lower():
                return {}
            data = json.loads(body)
        else:
            if not cdp_is_available():
                return {}
            response = cdp_fetch_jira_url(
                base,
                self.jql_var.get().strip(),
                f"/rest/api/2/issue/{urllib.parse.quote(key)}?fields={fields}",
                timeout=20,
            )
            status = int(response.get("status") or 0)
            ctype = str(response.get("contentType") or "")
            if status != 200 or "json" not in ctype.lower():
                return {}
            data = json.loads(str(response.get("text") or "{}"))
        self.jira_issue_detail_cache[key] = data
        return data

    def enrich_issue_with_qa_design_refs(
        self,
        issue: dict[str, Any],
        fetch_details: bool = True,
        max_details: int | None = None,
    ) -> None:
        design_issues = list(issue.get("qa_design_issues") or [])
        if not design_issues:
            issue["qa_doc_refs"] = dedupe_keep_order(issue.get("qa_doc_refs") or [])
            issue.setdefault("qa_design_details", [])
            return
        refs: list[str] = list(issue.get("qa_doc_refs") or [])
        details: list[dict[str, Any]] = []
        for detail_index, record in enumerate(design_issues):
            if not isinstance(record, dict):
                continue
            if max_details is not None and detail_index >= max_details:
                break
            key = str(record.get("key") or "").strip().upper()
            if not key:
                continue
            detail = {
                "key": key,
                "summary": str(record.get("summary") or ""),
                "status": str(record.get("status") or ""),
                "relation": str(record.get("relation") or ""),
                "refs": [],
                "fetch_status": "not fetched",
            }
            if not fetch_details:
                detail["fetch_status"] = "deferred"
                details.append(detail)
                continue
            data = self.fetch_issue_json_detail_for_qa(key)
            fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
            if fields:
                parsed_refs = extract_jira_qa_refs(fields)
                refs.extend(parsed_refs)
                detail["summary"] = str(fields.get("summary") or detail["summary"])
                status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
                detail["status"] = str(status.get("name") or detail["status"])
                detail["refs"] = parsed_refs
                detail["fetch_status"] = "ok"
            else:
                detail["fetch_status"] = "unavailable"
            details.append(detail)
        issue["qa_doc_refs"] = dedupe_keep_order(refs)
        issue["qa_design_details"] = details
        if fetch_details:
            issue["_qa_details_resolved"] = True

    def detect_jira_qa_fields_clicked(self) -> None:
        self.save_current_config()
        base = self.jira_url_var.get().strip() or DEFAULT_JIRA_URL
        fields_data: Any = None
        try:
            if self.jira_cookie_var.get().strip():
                status, ctype, body = jira_request(base, "/rest/api/2/field", self.jira_cookie_var.get().strip(), timeout=30)
                if status != 200 or "json" not in ctype.lower():
                    raise RuntimeError(f"Jira field API failed: HTTP {status} {ctype}")
                fields_data = json.loads(body)
            else:
                if not cdp_is_available():
                    self.open_dedicated_jira_browser(show_message=True)
                    return
                response = cdp_fetch_jira_url(base, self.jql_var.get().strip(), "/rest/api/2/field", timeout=60)
                status = int(response.get("status") or 0)
                ctype = str(response.get("contentType") or "")
                body = str(response.get("text") or "")
                if status != 200 or "json" not in ctype.lower():
                    raise RuntimeError(f"Jira field API failed in dedicated browser: HTTP {status} {ctype}")
                fields_data = json.loads(body)
        except Exception as exc:
            messagebox.showerror("Detect QA Fields", str(exc)[:4000])
            return

        if not isinstance(fields_data, list):
            messagebox.showinfo("Detect QA Fields", "Jira field API returned an unexpected response.")
            return
        detected = [
            str(field.get("id") or "").strip()
            for field in fields_data
            if isinstance(field, dict) and jira_field_matches_qa_hint(field) and str(field.get("id") or "").strip()
        ]
        self.jira_qa_fields = sorted(set(self.jira_qa_fields + detected))
        self.save_current_config()
        names = [
            f"{field.get('id')}: {field.get('name')}"
            for field in fields_data
            if isinstance(field, dict) and str(field.get("id") or "").strip() in self.jira_qa_fields
        ]
        self.status_var.set(f"Detected {len(detected)} QA-related Jira fields. Active extra fields: {len(self.jira_qa_fields)}")
        messagebox.showinfo(
            "Detect QA Fields",
            ("Detected QA-related fields:\n\n" + "\n".join(names[:40])) if names else "No QA-related custom fields found.",
        )

    def try_load_index_silent(self) -> None:
        if INDEX_PATH.exists():
            try:
                self.index = load_index()
                ensure_design_index_lookup(self.index)
                self.update_summary()
                self.status_var.set(f"Loaded existing index: {INDEX_PATH}")
            except Exception:
                pass

    def try_load_qa_index_silent(self) -> None:
        if QA_INDEX_PATH.exists():
            try:
                self.qa_index = load_qa_index()
                self.update_summary()
                self.status_var.set(f"Loaded existing QA index: {QA_INDEX_PATH}")
            except Exception:
                pass

    def try_load_jira_cache_silent(self) -> None:
        if not JIRA_CACHE_PATH.exists():
            return
        try:
            cache = load_jira_issue_cache()
            issues = cache.get("issues") or []
            self.issues = []
            for issue in issues:
                if isinstance(issue, dict):
                    self.add_or_replace_issue(issue, refresh=False)
            self.jira_cache_meta = cache.get("metadata") or {}
            if self.qa_index:
                for issue in self.issues:
                    if issue.get("qa_doc_refs"):
                        self.attach_qa_to_issue(issue)
            self.refresh_filter_options()
            self.refresh_issue_table()
            self.update_summary()
            generated_at = self.jira_cache_meta.get("generated_at", "unknown time")
            self.status_var.set(f"Loaded Jira cache: {len(self.issues)} issues from {generated_at}. Use One Click Refresh Jira when you need current data.")
        except Exception as exc:
            self.status_var.set(f"Failed to load Jira cache: {exc}")

    def load_jira_cache_clicked(self) -> None:
        if not JIRA_CACHE_PATH.exists():
            messagebox.showinfo("Load Jira Cache", f"No Jira cache exists yet.\n\nRefresh Jira once to create:\n{JIRA_CACHE_PATH}")
            return
        self.try_load_jira_cache_silent()
        messagebox.showinfo(
            "Load Jira Cache",
            f"Loaded {len(self.issues)} cached Jira issues.\n\n"
            f"Cache time: {self.jira_cache_meta.get('generated_at', '-')}\n"
            f"Source: {self.jira_cache_meta.get('source', '-')}\n\n"
            "Risk: cached status, assignee, links, and QA refs may be stale until you refresh Jira.",
        )

    def save_jira_cache_now(self, source: str) -> None:
        try:
            self.jira_cache_meta = save_jira_issue_cache(
                self.issues,
                jira_url=self.jira_url_var.get().strip() or DEFAULT_JIRA_URL,
                jql=self.jql_var.get().strip(),
                source=source,
            )
            self.update_summary()
        except Exception as exc:
            self.status_var.set(f"Jira cache save failed: {exc}")

    def cached_issue_for_id(self, issue_id: str) -> dict[str, Any] | None:
        for issue in self.issues:
            if issue.get("id") == issue_id or issue.get("key") == issue_id:
                return issue
        return None

    def apply_refreshed_jira_issue(self, issue: dict[str, Any]) -> str:
        issue["id"] = issue.get("key") or f"ISSUE-{len(self.issues) + 1}"
        existing = self.cached_issue_for_id(str(issue["id"]))
        if existing and jira_issue_unchanged(existing, issue):
            normalize_issue_match_state(existing)
            return "unchanged"
        match_input_changed = (
            existing is not None
            and issue_has_persisted_match(existing)
            and jira_match_input_signature(existing) != jira_match_input_signature(issue)
        )
        result = "updated" if existing else "new"
        self.add_or_replace_issue(issue, refresh=False)
        stored = self.cached_issue_for_id(str(issue["id"]))
        if stored and match_input_changed:
            stored["match_status"] = MATCH_STATUS_NEEDS_REMATCH
            old_reason = str(stored.get("reason") or "").strip()
            note = "Jira matching inputs changed after the local match. Run Match All Issues when you want to refresh design evidence."
            stored["reason"] = f"{old_reason}; {note}" if old_reason and note not in old_reason else note
        return result

    def load_index_clicked(self) -> None:
        try:
            self.index = load_index()
            ensure_design_index_lookup(self.index)
            if QA_INDEX_PATH.exists():
                self.qa_index = load_qa_index()
        except Exception as exc:
            messagebox.showerror("Load Index", str(exc))
            return
        self.update_summary()
        messagebox.showinfo(
            "Load Index",
            f"Loaded {len(self.index.get('requirements', []))} audio candidates and {len(self.qa_index.get('cases', []))} QA cases.",
        )

    def scan_qa_async(self) -> None:
        root = Path(self.design_root_var.get().strip())
        if not root.exists():
            messagebox.showerror("Scan QA", f"Design root not found:\n{root}")
            return
        self.save_current_config()
        self.status_var.set("Scanning QA acceptance docs...")
        self.disable_buttons(True)
        thread = threading.Thread(target=self._scan_qa_worker, args=(root,), daemon=True)
        thread.start()

    def _scan_qa_worker(self, root: Path) -> None:
        try:
            index = build_qa_acceptance_index(root, progress=lambda msg: self.after(0, self.status_var.set, msg))
            save_qa_index(index)
            self.qa_index = index
            self.after(0, self.on_qa_scan_complete, None)
        except Exception as exc:
            self.after(0, self.on_qa_scan_complete, exc)

    def on_qa_scan_complete(self, error: Exception | None) -> None:
        self.disable_buttons(False)
        if error:
            self.status_var.set(f"QA scan failed: {error}")
            messagebox.showerror("Scan QA", str(error))
            return
        if self.issues:
            for issue in self.issues:
                self.attach_qa_to_issue(issue)
            self.refresh_issue_table()
            selected = self.selected_issues()
            if selected:
                self.refresh_evidence_table(selected[0])
            self.save_jira_cache_now("QA scan rematch")
        self.update_summary()
        summary = self.qa_index.get("summary", {})
        self.status_var.set(f"QA scan complete. Docs: {summary.get('files_scanned', 0)} Cases: {summary.get('cases', 0)}")
        messagebox.showinfo("Scan QA", json.dumps(summary, ensure_ascii=False, indent=2)[:4000])

    def show_quick_start(self) -> None:
        messagebox.showinfo(
            "How To Use",
            "\n".join([
                "1. The design index is already loaded when the top-right summary shows Index docs/chunks/requirements.",
                "2. Click Open Dedicated Jira. Log into Jira once in that separate Edge window.",
                "3. Click One Click Refresh Jira. The tool will reuse the dedicated Jira browser session.",
                "4. On startup the tool loads the last Jira cache automatically. Refresh only when you need current Jira status, links, or QA refs.",
                "5. Keep or edit the JQL, for example: assignee = yupeng AND statusCategory != Done ORDER BY updated DESC",
                "6. Sync JQL uses the optional Cookie field. One Click Refresh Jira uses the dedicated browser first.",
                "7. If browser sync is blocked by local policy, export CSV from Jira, then click Import Jira CSV.",
                "8. Match All Issues classifies the loaded issues and saves the matched cache automatically.",
                "9. NotMatched means the row has not been matched yet. NoEvidence means matching ran but found no local design evidence.",
                "10. If Jira auth is unavailable, paste one issue into Manual Jira text / notes, then click Paste Jira Text.",
            ]),
        )

    def use_jira_url_clicked(self) -> None:
        candidate = ""
        try:
            candidate = self.clipboard_get().strip()
        except Exception:
            candidate = ""
        if "jql=" not in candidate.lower():
            candidate = simpledialog.askstring("Use Jira URL", "Paste Jira issue navigator URL:", parent=self) or ""
        jql, base_url = extract_jql_from_jira_url(candidate)
        if not jql:
            messagebox.showinfo("Use Jira URL", "No jql= parameter found in the URL.")
            return
        self.jql_var.set(jql)
        if base_url:
            self.jira_url_var.set(base_url)
        self.save_current_config()
        self.status_var.set("Jira URL decoded into JQL. Click Sync JQL when Jira auth is available.")
        messagebox.showinfo("Use Jira URL", "Decoded JQL:\n\n" + jql[:3000])

    def normalize_jql_from_url_if_needed(self) -> bool:
        raw = self.jql_var.get().strip()
        if "jql=" in raw.lower():
            jql, base_url = extract_jql_from_jira_url(raw)
            if jql:
                self.jql_var.set(jql)
                if base_url:
                    self.jira_url_var.set(base_url)
                return True
        if not raw:
            try:
                clip = self.clipboard_get().strip()
            except Exception:
                clip = ""
            if "jql=" in clip.lower():
                jql, base_url = extract_jql_from_jira_url(clip)
                if jql:
                    self.jql_var.set(jql)
                    if base_url:
                        self.jira_url_var.set(base_url)
                    return True
        return False

    def open_dedicated_jira_browser_clicked(self) -> None:
        self.normalize_jql_from_url_if_needed()
        self.open_dedicated_jira_browser(show_message=True)

    def restart_dedicated_jira_browser_clicked(self) -> None:
        self.normalize_jql_from_url_if_needed()
        self.close_dedicated_jira_browser_processes()
        time.sleep(1.0)
        self.open_dedicated_jira_browser(show_message=True)

    def open_dedicated_jira_browser(self, show_message: bool = False) -> None:
        base = self.jira_url_var.get().strip() or DEFAULT_JIRA_URL
        jql = self.jql_var.get().strip()
        try:
            if cdp_is_available():
                cdp_new_tab(jira_issue_navigator_url(base, jql))
            else:
                start_dedicated_jira_browser(base, jql)
        except Exception as exc:
            messagebox.showerror("Open Dedicated Jira", str(exc)[:4000])
            return
        self.save_current_config()
        self.status_var.set(
            f"Dedicated Jira browser opened. Profile: {DEDICATED_JIRA_PROFILE_DIR}. Log in there once, then click One Click Refresh Jira."
        )
        if show_message:
            messagebox.showinfo(
                "Open Dedicated Jira",
                "A separate Edge window has been opened for this tool.\n\n"
                "Log into Jira in that window once. After that, click One Click Refresh Jira.\n\n"
                f"Profile:\n{DEDICATED_JIRA_PROFILE_DIR}",
            )

    def close_dedicated_jira_browser_processes(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = (
            "Get-CimInstance Win32_Process -Filter \"name = 'msedge.exe'\" | "
            "Where-Object { $_.CommandLine -like '*jira_browser_profile*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            creationflags=flags,
            timeout=10,
        )

    def sync_jql_via_dedicated_browser(self, open_if_missing: bool = False) -> bool:
        base = self.jira_url_var.get().strip() or DEFAULT_JIRA_URL
        jql = self.jql_var.get().strip()
        if not jql:
            messagebox.showinfo("Dedicated Jira", "Enter JQL first.")
            return False
        if not cdp_is_available():
            if open_if_missing:
                self.open_dedicated_jira_browser(show_message=True)
            return False
        try:
            limit = max(1, int(self.jql_limit_var.get().strip() or "500"))
        except ValueError:
            limit = 500
            self.jql_limit_var.set(str(limit))
        page_size = min(50, limit)
        start_at = 0
        fetched = 0
        total = None
        refresh_counts = Counter()
        while fetched < limit:
            params = urllib.parse.urlencode({
                "jql": jql,
                "startAt": str(start_at),
                "maxResults": str(min(page_size, limit - fetched)),
                "fields": self.jira_fields_param(),
            })
            response = cdp_fetch_jira_url(base, jql, f"/rest/api/2/search?{params}", timeout=90)
            status = int(response.get("status") or 0)
            ctype = str(response.get("contentType") or "")
            body = str(response.get("text") or "")
            if status != 200 or "json" not in ctype.lower():
                if is_jira_login_page(body, str(response.get("title") or "")):
                    self.open_dedicated_jira_browser(show_message=False)
                    messagebox.showinfo(
                        "Dedicated Jira",
                        "The dedicated Jira browser is open, but Jira still returns the login page.\n\n"
                        "Please log into Jira in that dedicated Edge window, then click One Click Refresh Jira again.",
                    )
                    return False
                title = str(response.get("title") or "")
                messagebox.showerror(
                    "Dedicated Jira",
                    f"Jira REST search failed in the dedicated browser: HTTP {status} {ctype}\n"
                    f"Title: {title}\n\n"
                    "Open the dedicated Jira browser and confirm the issue list is visible, then try again.",
                )
                return False
            data = json.loads(body)
            raw_issues = data.get("issues", [])
            if total is None:
                total = int(data.get("total", len(raw_issues)) or 0)
            if not raw_issues:
                break
            for raw in raw_issues:
                issue = parse_issue_from_json(raw)
                issue["url"] = f"{base.rstrip()}/browse/{issue.get('key','')}"
                issue["source"] = "Jira REST via dedicated browser"
                self.enrich_issue_with_qa_design_refs(issue, fetch_details=False)
                refresh_counts[self.apply_refreshed_jira_issue(issue)] += 1
            fetched += len(raw_issues)
            start_at += len(raw_issues)
            self.status_var.set(
                f"Synced Jira from dedicated browser {fetched}/{total if total is not None else '?'} "
                f"(new {refresh_counts['new']}, updated {refresh_counts['updated']}, unchanged {refresh_counts['unchanged']})..."
            )
            self.update_idletasks()
            if start_at >= total:
                break
        self.refresh_filter_options()
        self.refresh_issue_table()
        self.update_summary()
        self.save_jira_cache_now("Jira REST via dedicated browser")
        self.status_var.set(
            f"Synced and cached {fetched} Jira issues via dedicated browser. "
            f"New:{refresh_counts['new']} Updated:{refresh_counts['updated']} Unchanged:{refresh_counts['unchanged']}. "
            "Click Match All Issues when you want design/audio classification."
        )
        return True

    def one_click_refresh_jira_clicked(self) -> None:
        decoded = self.normalize_jql_from_url_if_needed()
        if not self.jql_var.get().strip():
            messagebox.showinfo("One Click Refresh Jira", "JQL is empty. Paste a Jira issue navigator URL or enter JQL first.")
            return

        if not self.jira_cookie_var.get().strip():
            if not cdp_is_available():
                self.open_dedicated_jira_browser(show_message=True)
                return
            try:
                self.sync_jql_via_dedicated_browser(open_if_missing=False)
            except Exception as exc:
                messagebox.showerror("One Click Refresh Jira", f"Dedicated Jira browser sync failed:\n{exc}"[:4000])
            return

        if decoded:
            self.status_var.set("Decoded Jira URL into JQL. Syncing Jira...")
        self.sync_jql_clicked()

    def scan_design_async(self) -> None:
        self.start_design_scan(with_diff=False)

    def scan_diff_async(self) -> None:
        self.start_design_scan(with_diff=True)

    def cancel_scan_clicked(self) -> None:
        self.scan_cancel_requested = True
        self.status_var.set("Cancel requested. The scanner will stop after the current file.")

    def start_design_scan(self, with_diff: bool) -> None:
        root = Path(self.design_root_var.get().strip())
        if not root.exists():
            messagebox.showerror("Scan Design", f"Design root not found:\n{root}")
            return
        self.save_current_config()
        self.scan_cancel_requested = False
        self.status_var.set("Incremental scanning design docs..." + (" Then comparing changes." if with_diff else ""))
        mode = self.model_mode_var.get()
        try:
            diff_ai_limit = max(1, int(self.local_diff_limit_var.get().strip() or "20"))
        except ValueError:
            diff_ai_limit = 20
        self.disable_buttons(True)
        thread = threading.Thread(target=self._scan_design_worker, args=(root, with_diff, mode, diff_ai_limit), daemon=True)
        thread.start()

    def _scan_design_worker(self, root: Path, with_diff: bool, mode: str, diff_ai_limit: int) -> None:
        try:
            previous = load_index() if INDEX_PATH.exists() else {}
            index = build_design_index(
                root,
                progress=lambda msg: self.after(0, self.status_var.set, msg),
                previous_index=previous,
                should_cancel=lambda: self.scan_cancel_requested,
            )
            ensure_design_index_lookup(index)
            save_index(index)
            snapshot_path = save_snapshot(index)
            diff = {}
            report_paths: dict[str, str] = {}
            if with_diff and previous:
                diff = diff_indexes(previous, index)
                if mode in {"Local Ollama", "Hybrid"}:
                    self.after(0, self.status_var.set, "Running local AI review for top design changes...")
                    self.local_ai_review_diff_records(diff, limit=diff_ai_limit)
                report_paths = write_diff_reports(diff)
            elif with_diff:
                diff = {
                    "version": 1,
                    "generated_at": now_stamp(),
                    "design_root": str(root),
                    "summary": {"baseline_created": True, "message": "No previous index existed; current scan was saved as baseline."},
                    "new_audio_candidates": [],
                }
                report_paths = write_diff_reports(diff)
            self.index = index
            self.latest_diff = diff
            self.after(0, self.on_scan_complete, None, with_diff, snapshot_path, report_paths)
        except Exception as exc:
            self.after(0, self.on_scan_complete, exc, with_diff, None, {})

    def on_scan_complete(self, error: Exception | None, with_diff: bool = False, snapshot_path: Path | None = None, report_paths: dict[str, str] | None = None) -> None:
        self.scan_cancel_requested = False
        self.disable_buttons(False)
        if error:
            self.status_var.set(f"Scan failed: {error}")
            messagebox.showerror("Scan Design", str(error))
            return
        self.update_summary()
        summary = self.index.get("summary", {})
        if with_diff:
            diff_summary = (self.latest_diff or {}).get("summary", {})
            self.status_var.set(f"Scan+Diff complete. New audio candidates: {diff_summary.get('new_audio_candidates', 0)}")
            msg = {
                "scan_summary": summary,
                "diff_summary": diff_summary,
                "snapshot": str(snapshot_path or ""),
                "reports": report_paths or {},
            }
            messagebox.showinfo("Scan + Diff Changes", json.dumps(msg, ensure_ascii=False, indent=2)[:4000])
        else:
            self.status_var.set(
                f"Scan complete. Parsed:{summary.get('parsed_docs', 0)} Reused:{summary.get('reused_docs', 0)} "
                f"SkippedLarge:{summary.get('skipped_large_files', 0)} Requirements:{summary.get('requirements', 0)}"
            )
            messagebox.showinfo("Scan Design", json.dumps(summary, ensure_ascii=False, indent=2)[:4000])

    def disable_buttons(self, disabled: bool) -> None:
        state = tk.DISABLED if disabled else tk.NORMAL
        for child in self.winfo_children():
            self._set_button_state(child, state)

    def _set_button_state(self, widget: tk.Misc, state: str) -> None:
        if isinstance(widget, tk.Button):
            widget.configure(state=state)
        for child in widget.winfo_children():
            self._set_button_state(child, state)

    def update_summary(self) -> None:
        summary = self.index.get("summary", {})
        qa_summary = self.qa_index.get("summary", {})
        start_counts = Counter(issue.get("can_start", "Unknown") for issue in self.issues)
        start_bits = " ".join(f"{key}:{value}" for key, value in start_counts.items() if value)
        matched_count = sum(1 for issue in self.issues if issue_has_persisted_match(issue))
        unmatched_count = max(0, len(self.issues) - matched_count)
        cache_time = str(self.jira_cache_meta.get("generated_at") or "").replace("T", " ")
        cache_bits = f" cache:{cache_time[:16]}" if cache_time else " cache:none"
        self.summary_var.set(
            f"Index docs:{summary.get('files_scanned', 0)} chunks:{summary.get('chunks', 0)} "
            f"requirements:{summary.get('requirements', 0)} QA:{qa_summary.get('cases', 0)} "
            f"issues:{len(self.issues)} matched:{matched_count} unmatched:{unmatched_count}{cache_bits} {start_bits}"
        )

    def refresh_filter_options(self) -> None:
        def collect(field: str, split: bool = False) -> list[str]:
            values: set[str] = set()
            for issue in self.issues:
                raw = issue.get(field, "")
                parts = split_multi_values(raw) if split else [str(raw).strip()]
                for value in parts:
                    if value:
                        values.add(value)
            return sorted(values)

        def set_combo(combo: ttk.Combobox | None, var: tk.StringVar, values: list[str]) -> None:
            if combo is None:
                return
            all_values = ["All"] + values
            combo.configure(values=all_values)
            if var.get() not in all_values:
                var.set("All")

        set_combo(self.system_filter_combo, self.filter_system_var, collect("system"))
        set_combo(self.version_filter_combo, self.filter_version_var, collect("version_label"))
        set_combo(self.start_filter_combo, self.filter_start_var, collect("can_start"))
        set_combo(self.filter_combos.get("Audio"), self.filter_audio_var, collect("audio_required"))
        set_combo(self.filter_combos.get("Ready"), self.filter_ready_var, collect("ready_state"))
        set_combo(self.filter_combos.get("Status"), self.filter_status_var, collect("status"))
        set_combo(self.filter_combos.get("Type"), self.filter_type_var, collect("issue_type"))
        set_combo(self.filter_combos.get("Assignee"), self.filter_assignee_var, collect("assignee"))
        set_combo(self.filter_combos.get("Reporter"), self.filter_reporter_var, collect("reporter"))
        set_combo(self.filter_combos.get("Creator"), self.filter_creator_var, collect("creator"))
        set_combo(self.filter_combos.get("Priority"), self.filter_priority_var, collect("priority"))
        set_combo(self.filter_combos.get("Design Area"), self.filter_design_area_var, collect("design_area"))
        set_combo(self.filter_combos.get("Design Doc"), self.filter_design_doc_var, collect("design_doc"))
        set_combo(self.filter_combos.get("Dependency"), self.filter_dependency_var, collect("dependency_label", split=True))
        set_combo(self.filter_combos.get("Component"), self.filter_component_var, collect("components", split=True))
        set_combo(self.filter_combos.get("Label"), self.filter_label_var, collect("labels", split=True))

    def clear_filters(self) -> None:
        self.search_var.set("")
        for var in (
            self.filter_system_var,
            self.filter_version_var,
            self.filter_start_var,
            self.filter_audio_var,
            self.filter_ready_var,
            self.filter_status_var,
            self.filter_type_var,
            self.filter_assignee_var,
            self.filter_reporter_var,
            self.filter_creator_var,
            self.filter_priority_var,
            self.filter_design_area_var,
            self.filter_design_doc_var,
            self.filter_dependency_var,
            self.filter_component_var,
            self.filter_label_var,
        ):
            var.set("All")
        self.refresh_issue_table()

    def compare_latest_snapshots(self) -> None:
        snapshots = list_snapshots()
        if len(snapshots) < 2:
            messagebox.showinfo("Compare Latest", "Need at least two design snapshots. Run Scan + Diff Changes after a design update.")
            return
        try:
            old = json.loads(snapshots[-2].read_text(encoding="utf-8"))
            new = json.loads(snapshots[-1].read_text(encoding="utf-8"))
            diff = diff_indexes(old, new)
            mode = self.model_mode_var.get()
            if mode in {"Local Ollama", "Hybrid"}:
                self.local_ai_review_diff_records(diff)
            paths = write_diff_reports(diff)
            self.latest_diff = diff
        except Exception as exc:
            messagebox.showerror("Compare Latest", str(exc)[:4000])
            return
        self.status_var.set(f"Compared latest snapshots. New audio candidates: {diff.get('summary', {}).get('new_audio_candidates', 0)}")
        messagebox.showinfo("Compare Latest", json.dumps({"summary": diff.get("summary", {}), "reports": paths}, ensure_ascii=False, indent=2)[:4000])

    def open_latest_diff(self) -> None:
        if LATEST_DIFF_PATH.exists():
            os.startfile(str(LATEST_DIFF_PATH))
        else:
            messagebox.showinfo("Open Diff", "No diff report yet. Run Scan + Diff Changes or Compare Latest first.")

    def local_ai_diff_clicked(self) -> None:
        if not self.latest_diff:
            if LATEST_DIFF_PATH.exists():
                self.latest_diff = json.loads(LATEST_DIFF_PATH.read_text(encoding="utf-8"))
            else:
                messagebox.showinfo("Local AI Diff", "No diff loaded. Run Scan + Diff Changes or Compare Latest first.")
                return
        try:
            limit = max(1, int(self.local_diff_limit_var.get().strip() or "20"))
        except ValueError:
            limit = 20
        try:
            updated = self.local_ai_review_diff_records(self.latest_diff, limit=limit)
            paths = write_diff_reports(self.latest_diff)
        except Exception as exc:
            messagebox.showerror("Local AI Diff", str(exc)[:4000])
            return
        self.status_var.set(f"Local AI reviewed {updated} design-change candidates. Reports refreshed.")
        messagebox.showinfo("Local AI Diff", json.dumps({"reviewed": updated, "reports": paths}, ensure_ascii=False, indent=2)[:4000])

    def local_ai_review_diff_records(self, diff: dict[str, Any], limit: int | None = None) -> int:
        records = diff.get("new_audio_candidates", [])
        if limit is None:
            try:
                limit = max(1, int(self.local_diff_limit_var.get().strip() or "20"))
            except ValueError:
                limit = 20
        updated = 0
        for record in records[:limit]:
            if record.get("local_ai"):
                continue
            result = self.local_ai_review_change(record)
            record["local_ai"] = result
            if result.get("audio_required"):
                record["audio_required"] = result.get("audio_required")
            if result.get("ready_state"):
                record["ai_ready_state"] = result.get("ready_state")
            if result.get("reason"):
                record["ai_reason"] = result.get("reason")
            updated += 1
        diff["local_ai_reviewed_at"] = now_stamp()
        diff["local_ai_reviewed_count"] = updated
        return updated

    def local_ai_review_change(self, record: dict[str, Any]) -> dict[str, Any]:
        url = self.ollama_url_var.get().strip().rstrip("/") or DEFAULT_OLLAMA_URL
        model = self.local_model_var.get().strip() or DEFAULT_LOCAL_MODEL
        prompt = (
            "You are a conservative game-audio production change monitor.\n"
            "A design document changed and produced this possible new audio requirement.\n"
            "Judge whether this creates real new audio work. If evidence is weak, use Maybe or Unknown.\n"
            "Return strict JSON only with keys: audio_required, ready_state, confidence, audio_impact, reason, question.\n"
            "Allowed audio_required: Yes, Maybe, No, Unknown.\n"
            "Allowed ready_state: Ready, DesignOnly, Blocked, Risky, Cuttable, UnknownNeedsDesign.\n"
            "Allowed audio_impact: NoAudioImpact, ResourceOnly, WwiseOnly, UnityOnly, MixOnly, FullPipeline, UnknownNeedsQuestion.\n\n"
            f"Source: {record.get('doc_path','')} {record.get('locator','')}\n"
            f"Rule SABC: {record.get('sabc','')} Ready: {record.get('ready_state','')} Type: {record.get('sound_type','')} Score: {record.get('audio_score','')}\n"
            f"Rule reason: {record.get('reason','')}\n"
            f"Evidence:\n{clean_text(record.get('evidence',''))[:2500]}"
        )
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 700},
        }
        request = urllib.request.Request(
            f"{url}/api/generate",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        return extract_json(data.get("response", ""))

    def use_browser_login_clicked(self) -> None:
        try:
            header, source, count = import_browser_jira_cookie_header(self.jira_url_var.get().strip())
        except Exception as exc:
            messagebox.showerror("Use Browser Login", str(exc)[:4000])
            return
        if not header:
            messagebox.showinfo(
                "Use Browser Login",
                source + "\n\nOpen Jira in Chrome or Edge, confirm you are logged in, then click this button again.",
            )
            return
        self.jira_cookie_var.set(header)
        self.status_var.set(f"Loaded {count} Jira browser cookies from {source}. Cookie is used in this window only and is not saved.")
        self.test_jira()

    def close_edge_then_login_clicked(self) -> None:
        if not messagebox.askyesno(
            "Close Edge + Login",
            "This will close all Microsoft Edge windows and background msedge.exe processes.\n\nUnsaved web page state may be lost.\n\nContinue?",
            parent=self,
        ):
            return
        self.close_edge_processes()
        time.sleep(1.5)
        self.use_browser_login_clicked()

    def close_edge_processes(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["taskkill", "/IM", "msedge.exe", "/F"],
            capture_output=True,
            text=True,
            creationflags=flags,
        )

    def test_jira(self) -> None:
        self.save_current_config()
        base = self.jira_url_var.get().strip()
        cookie = self.jira_cookie_var.get().strip()
        status, ctype, body = jira_request(base, "/browse/PROEF-9209?filter=-1", cookie, timeout=10)
        title = ""
        if re.search(r"<title>(.*?)</title>", body, re.I | re.S):
            title = strip_html(re.search(r"<title>(.*?)</title>", body, re.I | re.S).group(1)).strip()
        message = f"HTTP {status}\nContent-Type: {ctype}\nTitle: {title}\nLength: {len(body)}"
        if is_jira_login_page(body, title):
            message += "\n\nJira is reachable, but it is returning the login page. Paste a logged-in Cookie or use Paste Jira Text."
        self.status_var.set(message.replace("\n", " | ")[:1000])
        messagebox.showinfo("Test Jira", message[:4000])

    def sync_issue_clicked(self) -> None:
        key = self.issue_key_var.get().strip().upper()
        if not key:
            messagebox.showinfo("Sync Issue", "Enter an issue key first.")
            return
        self.save_current_config()
        try:
            if self.jira_cookie_var.get().strip():
                issue = self.fetch_issue(key)
            else:
                if not cdp_is_available():
                    self.open_dedicated_jira_browser(show_message=True)
                    return
                issue = self.fetch_issue_via_dedicated_browser(key)
        except Exception as exc:
            messagebox.showerror("Sync Issue", str(exc)[:4000])
            return
        self.add_or_replace_issue(issue)
        self.match_all_issues(on_complete=lambda: self.save_jira_cache_now("Jira single issue"))

    def import_jira_csv_clicked(self) -> None:
        selected = filedialog.askopenfilename(
            title="Import Jira CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self,
        )
        if not selected:
            return
        path = Path(selected)
        last_error = None
        rows: list[dict[str, str]] = []
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    rows = list(csv.DictReader(handle))
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            messagebox.showerror("Import Jira CSV", str(last_error)[:4000])
            return
        count = 0
        for index, row in enumerate(rows, 1):
            if not row:
                continue
            issue = parse_issue_from_csv_row(row, index)
            self.add_or_replace_issue(issue, refresh=False)
            count += 1
        if self.index:
            def after_match() -> None:
                self.save_jira_cache_now(f"Jira CSV: {path.name}")
                self.status_var.set(f"Imported, matched, and cached {count} Jira issues from CSV: {path}")
                messagebox.showinfo("Import Jira CSV", f"Imported, matched, and cached {count} Jira issues.\n\n{path}")

            self.match_all_issues(on_complete=after_match)
            return
        else:
            self.refresh_filter_options()
            self.refresh_issue_table()
            self.update_summary()
        self.save_jira_cache_now(f"Jira CSV: {path.name}")
        self.status_var.set(f"Imported and cached {count} Jira issues from CSV: {path}")
        messagebox.showinfo("Import Jira CSV", f"Imported and cached {count} Jira issues.\n\n{path}")

    def fetch_issue(self, key: str) -> dict[str, Any]:
        base = self.jira_url_var.get().strip()
        cookie = self.jira_cookie_var.get().strip()
        status, ctype, body = jira_request(base, f"/rest/api/2/issue/{urllib.parse.quote(key)}", cookie, timeout=20)
        if status == 200 and "json" in ctype.lower():
            data = json.loads(body)
            issue = parse_issue_from_json(data)
            issue["url"] = f"{base.rstrip()}/browse/{key}"
            self.enrich_issue_with_qa_design_refs(issue)
            return issue
        status, ctype, body = jira_request(base, f"/browse/{urllib.parse.quote(key)}?filter=-1", cookie, timeout=20)
        issue = parse_issue_from_html(body, key)
        issue["url"] = f"{base.rstrip()}/browse/{key}"
        title = issue.get("summary", "")
        if is_jira_login_page(body, title):
            raise RuntimeError("Jira is reachable but returned the login page. Paste a logged-in Cookie, or paste the issue text manually.")
        return issue

    def fetch_issue_via_dedicated_browser(self, key: str) -> dict[str, Any]:
        base = self.jira_url_var.get().strip() or DEFAULT_JIRA_URL
        fields = urllib.parse.quote(self.jira_fields_param(), safe=",")
        response = cdp_fetch_jira_url(base, self.jql_var.get().strip(), f"/rest/api/2/issue/{urllib.parse.quote(key)}?fields={fields}", timeout=60)
        status = int(response.get("status") or 0)
        ctype = str(response.get("contentType") or "")
        body = str(response.get("text") or "")
        if status == 200 and "json" in ctype.lower():
            issue = parse_issue_from_json(json.loads(body))
            issue["url"] = f"{base.rstrip()}/browse/{key}"
            issue["source"] = "Jira REST via dedicated browser"
            self.enrich_issue_with_qa_design_refs(issue)
            return issue
        if is_jira_login_page(body, str(response.get("title") or "")):
            self.open_dedicated_jira_browser(show_message=False)
            raise RuntimeError("The dedicated Jira browser is open, but Jira still returns the login page. Log into Jira there, then try Sync Issue again.")
        title = str(response.get("title") or "")
        raise RuntimeError(f"Jira issue fetch failed in the dedicated browser: HTTP {status} {ctype}\nTitle: {title}")

    def sync_jql_clicked(self) -> None:
        self.save_current_config()
        base = self.jira_url_var.get().strip()
        cookie = self.jira_cookie_var.get().strip()
        jql = self.jql_var.get().strip()
        if not jql:
            messagebox.showinfo("Sync JQL", "Enter JQL first.")
            return
        try:
            limit = max(1, int(self.jql_limit_var.get().strip() or "500"))
        except ValueError:
            limit = 500
            self.jql_limit_var.set(str(limit))
        page_size = min(100, limit)
        start_at = 0
        fetched = 0
        total = None
        refresh_counts = Counter()
        while fetched < limit:
            params = urllib.parse.urlencode({
                "jql": jql,
                "startAt": str(start_at),
                "maxResults": str(min(page_size, limit - fetched)),
                "fields": self.jira_fields_param(),
            })
            status, ctype, body = jira_request(base, f"/rest/api/2/search?{params}", cookie, timeout=60)
            if status != 200 or "json" not in ctype.lower():
                title = ""
                if re.search(r"<title>(.*?)</title>", body, re.I | re.S):
                    title = strip_html(re.search(r"<title>(.*?)</title>", body, re.I | re.S).group(1)).strip()
                messagebox.showerror("Sync JQL", f"Jira REST search failed: HTTP {status} {ctype}\nTitle: {title}\n\nPaste a logged-in Cookie or use Paste Jira Text.")
                return
            data = json.loads(body)
            raw_issues = data.get("issues", [])
            if total is None:
                total = int(data.get("total", len(raw_issues)) or 0)
            if not raw_issues:
                break
            for raw in raw_issues:
                issue = parse_issue_from_json(raw)
                issue["url"] = f"{base.rstrip()}/browse/{issue.get('key','')}"
                self.enrich_issue_with_qa_design_refs(issue, fetch_details=False)
                refresh_counts[self.apply_refreshed_jira_issue(issue)] += 1
            fetched += len(raw_issues)
            start_at += len(raw_issues)
            self.status_var.set(
                f"Synced Jira {fetched}/{total if total is not None else '?'} "
                f"(new {refresh_counts['new']}, updated {refresh_counts['updated']}, unchanged {refresh_counts['unchanged']})..."
            )
            self.update_idletasks()
            if start_at >= total:
                break
        self.refresh_filter_options()
        self.refresh_issue_table()
        self.update_summary()
        self.save_jira_cache_now("Jira REST")
        self.status_var.set(
            f"Synced and cached {fetched} Jira issues. "
            f"New:{refresh_counts['new']} Updated:{refresh_counts['updated']} Unchanged:{refresh_counts['unchanged']}. "
            "Click Match All Issues when you want design/audio classification."
        )

    def paste_jira_text(self) -> None:
        text = self.manual_text.get("1.0", tk.END).strip()
        if not text:
            text = simpledialog.askstring("Paste Jira Text", "Paste summary/description text:", parent=self) or ""
        if not text.strip():
            return
        key = self.issue_key_var.get().strip().upper() or f"MANUAL-{len(self.issues) + 1}"
        issue = issue_from_manual_text(key, text)
        self.add_or_replace_issue(issue)
        self.match_all_issues(on_complete=lambda: self.save_jira_cache_now("Manual Jira text"))

    def add_or_replace_issue(self, issue: dict[str, Any], refresh: bool = True) -> None:
        issue["id"] = issue.get("key") or f"ISSUE-{len(self.issues) + 1}"
        existing_index = None
        existing_issue = None
        for idx, current in enumerate(self.issues):
            if current.get("id") == issue["id"]:
                existing_index = idx
                existing_issue = current
                break
        incoming_has_match = issue_has_persisted_match(issue)
        issue["version_label"] = issue_version_label(issue)
        issue.setdefault("can_start", "Unknown")
        issue.setdefault("system", "")
        issue.setdefault("design_area", UNMATCHED_DESIGN_LABEL)
        issue.setdefault("design_doc", "")
        issue.setdefault("dependency_label", dependency_label(issue))
        issue.setdefault("audio_required", "Unknown")
        issue.setdefault("ready_state", "Unknown")
        issue.setdefault("sound_type", "")
        issue.setdefault("issue_links", "")
        issue.setdefault("qa_doc_refs", [])
        issue.setdefault("qa_design_issues", [])
        issue.setdefault("qa_summary", "No QA")
        issue.setdefault("qa_path", "")
        issue.setdefault("qa_open_target", "")
        issue.setdefault("qa_link_status", "Not checked")
        issue.setdefault("reporter", "")
        issue.setdefault("creator", "")
        issue.setdefault("match_status", MATCH_STATUS_NOT_MATCHED)
        if existing_issue and issue_has_persisted_match(existing_issue) and not incoming_has_match:
            for field in MATCH_RESULT_FIELDS:
                if field in existing_issue:
                    issue[field] = existing_issue[field]
            issue["qa_doc_refs"] = dedupe_refs_prefer_full_paths(
                list(existing_issue.get("qa_doc_refs") or []) + list(issue.get("qa_doc_refs") or [])
            )
            if existing_issue.get("qa_design_details") and not issue.get("qa_design_details"):
                issue["qa_design_details"] = existing_issue.get("qa_design_details")
            issue["dependency_label"] = dependency_label(issue)
        normalize_issue_match_state(issue)
        if existing_index is not None:
            self.issues[existing_index] = issue
        else:
            self.issues.append(issue)
        if refresh:
            self.refresh_filter_options()
            self.refresh_issue_table()
            self.update_summary()

    def attach_qa_to_issue(self, issue: dict[str, Any]) -> None:
        refs = [str(item) for item in issue.get("qa_doc_refs") or []]
        design_root = Path(self.design_root_var.get().strip() or DEFAULT_DESIGN_ROOT)
        if not self.qa_index:
            issue["qa_cases"] = []
            issue["qa_summary"] = "No QA"
            issue["qa_path"] = summarize_qa_path_from_cases([], refs)
            issue["qa_open_target"] = first_qa_open_target([], refs, design_root)
            issue["qa_link_status"] = "QA index not loaded" if refs else "No QA ref"
            for item in issue.get("evidence") or []:
                item["qa_cases"] = []
                item["qa_summary"] = "No QA"
                item["qa_source"] = ""
                item["qa_path"] = ""
            return
        evidence = issue.get("evidence") or []
        inferred_docs: list[dict[str, Any]] = []
        if not refs:
            inferred_docs = qa_documents_matching_issue_topic(self.qa_index, issue, evidence, limit=2)
            refs = dedupe_refs_prefer_full_paths(
                str(doc.get("full_path") or doc.get("path") or "")
                for doc in inferred_docs
                if str(doc.get("full_path") or doc.get("path") or "").strip()
            )
            if refs:
                issue["qa_doc_refs"] = refs
        explicit_docs = qa_documents_matching_refs(self.qa_index, refs)
        if not explicit_docs:
            inferred_docs = inferred_docs or qa_documents_matching_issue_topic(self.qa_index, issue, evidence, limit=2)
            inferred_refs = dedupe_refs_prefer_full_paths(
                str(doc.get("full_path") or doc.get("path") or "")
                for doc in inferred_docs
                if str(doc.get("full_path") or doc.get("path") or "").strip()
            )
            if inferred_refs:
                refs = dedupe_refs_prefer_full_paths(inferred_refs + refs)
                issue["qa_doc_refs"] = refs
                explicit_docs = inferred_docs
        doc_fallback_refs: list[str] = []
        for doc in explicit_docs:
            for key in ("full_path", "path"):
                value = str(doc.get(key) or "").strip()
                if value:
                    doc_fallback_refs.append(value)
        fallback_refs = dedupe_keep_order(doc_fallback_refs + refs)
        issue_cases = rank_qa_cases_for_issue(issue, self.qa_index, evidence, limit=80)
        issue["qa_cases"] = issue_cases
        issue["qa_summary"] = summarize_qa_cases(issue_cases)
        issue["qa_path"] = summarize_qa_path_from_cases(issue_cases, fallback_refs)
        issue["qa_open_target"] = first_qa_open_target(issue_cases, fallback_refs, design_root)
        if inferred_docs and issue_cases:
            issue["qa_link_status"] = "Inferred QA doc"
        elif inferred_docs:
            issue["qa_link_status"] = "Inferred QA path"
        elif explicit_docs and issue_cases:
            issue["qa_link_status"] = "Exact QA ref"
        elif refs and not issue_cases:
            issue["qa_link_status"] = "QA ref not indexed"
        elif refs:
            issue["qa_link_status"] = "QA ref weak"
        elif issue_cases:
            issue["qa_link_status"] = "Inferred QA"
        else:
            issue["qa_link_status"] = "No QA ref"
        for item in evidence:
            item_cases = issue_cases[:24]
            item["qa_cases"] = item_cases
            item["qa_summary"] = summarize_qa_cases(item_cases)
            item["qa_source"] = ", ".join(sorted(set(case.get("qa_source", "") for case in item_cases if case.get("qa_source"))))[:80]
            item["qa_path"] = summarize_qa_path_from_cases(item_cases, fallback_refs)

    def match_one_issue(self, issue: dict[str, Any]) -> None:
        evidence = rank_evidence(issue, self.index, limit=12)
        verdict = classify_issue(issue, evidence)
        issue["evidence"] = evidence
        issue.update(verdict)
        assign_issue_dimensions(issue)
        self.attach_qa_to_issue(issue)
        issue["match_status"] = MATCH_STATUS_MATCHED
        issue["matched_at"] = now_stamp()

    def match_all_issues(self, on_complete=None) -> None:
        if not self.index:
            messagebox.showinfo("Match", "Load or scan the design index first.")
            return
        if not self.issues:
            messagebox.showinfo("Match", "No Jira issues loaded yet. Click Sync JQL first, or paste an issue into Manual Jira text / notes and click Paste Jira Text.")
            return
        if self.matching_issues:
            messagebox.showinfo("Match", "Issue matching is already running.")
            return
        self.matching_issues = True
        self.match_index = 0
        self.match_after_complete = on_complete
        self.disable_buttons(True)
        self.status_var.set(f"Preparing fast design lookup for {len(self.issues)} Jira issues...")
        self.after(10, self.match_all_issues_step)

    def match_all_issues_step(self) -> None:
        if not self.matching_issues:
            return
        try:
            total = len(self.issues)
            batch_start = time.perf_counter()
            processed = 0
            while self.match_index < total and processed < 4 and (time.perf_counter() - batch_start) < 0.09:
                self.match_one_issue(self.issues[self.match_index])
                self.match_index += 1
                processed += 1
            self.status_var.set(f"Matching Jira issues {self.match_index}/{total} against design index and QA cases...")
            if self.match_index < total:
                self.after(15, self.match_all_issues_step)
                return
        except Exception as exc:
            self.matching_issues = False
            self.match_after_complete = None
            self.disable_buttons(False)
            self.status_var.set(f"Match failed: {exc}")
            messagebox.showerror("Match", str(exc)[:4000])
            return

        callback = self.match_after_complete
        self.matching_issues = False
        self.match_after_complete = None
        self.disable_buttons(False)
        self.refresh_filter_options()
        self.refresh_issue_table()
        self.update_summary()
        if callback:
            callback()
            self.status_var.set(f"Matched and cached {len(self.issues)} issues against design index and QA cases.")
        else:
            self.save_jira_cache_now("Local design/QA match")
            self.status_var.set(f"Matched and cached {len(self.issues)} issues against design index and QA cases.")

    def refresh_issue_table(self) -> None:
        self.issue_tree.delete(*self.issue_tree.get_children())
        query = self.search_var.get().strip().lower()
        def selected(var: tk.StringVar) -> str:
            value = var.get().strip()
            return "" if not value or value == "All" else value

        def matches_filter(issue: dict[str, Any], field: str, wanted: str, split: bool = False) -> bool:
            if not wanted:
                return True
            raw = issue.get(field, "")
            if split:
                return wanted in split_multi_values(raw)
            return str(raw).strip() == wanted

        self.visible_issue_iids.clear()
        for issue in self.issues:
            hay = " ".join(
                str(issue.get(k, ""))
                for k in (
                    "key",
                    "summary",
                    "audio_required",
                    "ready_state",
                    "can_start",
                    "system",
                    "version_label",
                    "design_area",
                    "design_doc",
                    "dependency_label",
                    "status",
                    "assignee",
                    "reporter",
                    "creator",
                    "issue_type",
                    "priority",
                    "components",
                    "labels",
                    "issue_links",
                    "qa_summary",
                    "qa_link_status",
                    "qa_path",
                    "qa_doc_refs",
                    "reason",
                )
            ).lower()
            if query and query not in hay:
                continue
            if not matches_filter(issue, "system", selected(self.filter_system_var)):
                continue
            if not matches_filter(issue, "version_label", selected(self.filter_version_var)):
                continue
            if not matches_filter(issue, "can_start", selected(self.filter_start_var)):
                continue
            if not matches_filter(issue, "audio_required", selected(self.filter_audio_var)):
                continue
            if not matches_filter(issue, "ready_state", selected(self.filter_ready_var)):
                continue
            if not matches_filter(issue, "status", selected(self.filter_status_var)):
                continue
            if not matches_filter(issue, "issue_type", selected(self.filter_type_var)):
                continue
            if not matches_filter(issue, "assignee", selected(self.filter_assignee_var)):
                continue
            if not matches_filter(issue, "reporter", selected(self.filter_reporter_var)):
                continue
            if not matches_filter(issue, "creator", selected(self.filter_creator_var)):
                continue
            if not matches_filter(issue, "priority", selected(self.filter_priority_var)):
                continue
            if not matches_filter(issue, "design_area", selected(self.filter_design_area_var)):
                continue
            if not matches_filter(issue, "design_doc", selected(self.filter_design_doc_var)):
                continue
            if not matches_filter(issue, "dependency_label", selected(self.filter_dependency_var), split=True):
                continue
            if not matches_filter(issue, "components", selected(self.filter_component_var), split=True):
                continue
            if not matches_filter(issue, "labels", selected(self.filter_label_var), split=True):
                continue
            iid = issue["id"]
            self.visible_issue_iids.append(iid)
            evidence = issue.get("evidence") or []
            best = evidence[0] if evidence else {}
            best_label = f"{best.get('doc_path','')} {best.get('locator','')}".strip()
            self.issue_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    issue.get("key", ""),
                    issue.get("audio_required", "-"),
                    issue.get("can_start", "-"),
                    issue.get("ready_state", "-"),
                    issue.get("system", ""),
                    issue.get("version_label", ""),
                    issue.get("design_area", ""),
                    issue.get("dependency_label", ""),
                    issue.get("qa_link_status", ""),
                    issue.get("qa_path", ""),
                    issue.get("confidence", "-"),
                    issue.get("status", ""),
                    issue.get("summary", ""),
                    best_label,
                ),
            )

    def selected_issues(self) -> list[dict[str, Any]]:
        selected = set(self.issue_tree.selection())
        return [issue for issue in self.issues if issue.get("id") in selected]

    def on_issue_selected(self) -> None:
        selected = self.selected_issues()
        if not selected:
            return
        issue = selected[0]
        self.show_issue_detail(issue)
        self.refresh_evidence_table(issue)
        self.update_selected_qa_path_label(issue)

    def update_selected_qa_path_label(self, issue: dict[str, Any] | None = None) -> None:
        if issue is None:
            selected = self.selected_issues()
            issue = selected[0] if selected else None
        if not issue:
            self.qa_path_var.set("QA Path: -")
            return
        item = self.current_evidence_item()
        item_path = str(item.get("qa_path") or "").strip() if item else ""
        label = item_path or str(issue.get("qa_path") or "").strip()
        status = str(issue.get("qa_link_status") or "Not checked")
        if not label:
            label = "-"
        self.qa_path_var.set(f"QA Path [{status}]: {label}"[:1200])

    def open_selected_jira_issue(self) -> None:
        selected = self.selected_issues()
        if not selected:
            return
        issue = selected[0]
        key = str(issue.get("key") or issue.get("id") or "").strip()
        url = str(issue.get("url") or "").strip()
        if not url and key:
            url = f"{(self.jira_url_var.get().strip() or DEFAULT_JIRA_URL).rstrip('/')}/browse/{urllib.parse.quote(key)}"
        if not url:
            messagebox.showinfo("Open Jira", "Selected row has no Jira URL or key.")
            return
        try:
            if cdp_is_available():
                cdp_new_tab(url)
            else:
                start_dedicated_jira_browser_url(url)
            self.status_var.set(f"Opened Jira issue: {url}")
        except Exception as exc:
            try:
                os.startfile(url)
                self.status_var.set(f"Opened Jira issue in default browser: {url}")
            except Exception:
                messagebox.showerror("Open Jira", f"Could not open Jira issue:\n{url}\n\n{exc}"[:4000])

    def show_issue_detail(self, issue: dict[str, Any]) -> None:
        evidence = issue.get("evidence") or []
        self.selected_summary_var.set(
            " | ".join(
                part
                for part in (
                    f"{issue.get('key','')}: {issue.get('summary','')}",
                    f"Status {issue.get('status','-')}",
                    f"Reporter {issue.get('reporter','-')}",
                    f"Creator {issue.get('creator','-')}",
                    f"Design {issue.get('design_area','-')}",
                    f"Dependency {issue.get('dependency_label','-')}",
                )
                if part.strip()
            )[:900]
        )
        lines = [
            f"Jira: {issue.get('key','')}  Source: {issue.get('source','')}",
            f"Summary: {issue.get('summary','')}",
            f"Status: {issue.get('status','-')}  Assignee: {issue.get('assignee','-')}  Reporter: {issue.get('reporter','-')}  Creator: {issue.get('creator','-')}  Updated: {issue.get('updated','-')}",
            f"Version: {issue.get('version_label','-')}  Component: {issue.get('components','-')}  Label: {issue.get('labels','-')}",
            f"Type: {issue.get('issue_type','-')}  Priority: {issue.get('priority','-')}  Dependency: {issue.get('dependency_label','-')}",
            f"Design Area: {issue.get('design_area','-')}  Design Doc: {issue.get('design_doc','-')}",
            f"System: {issue.get('system','-')}  Sound Type: {issue.get('sound_type','-')}  Can Start: {issue.get('can_start','-')}",
            f"Audio Required: {issue.get('audio_required','-')}  Ready: {issue.get('ready_state','-')}  Confidence: {issue.get('confidence','-')}",
            f"QA: {issue.get('qa_summary','No QA')}",
            f"QA Link Status: {issue.get('qa_link_status','Not checked')}",
            f"QA Path: {issue.get('qa_path','') or '-'}",
            f"Reason: {issue.get('reason','-')}",
            "",
            "Top Evidence:",
        ]
        qa_design_details = issue.get("qa_design_details") or []
        if qa_design_details:
            lines.extend(["", "Jira Test Case Design Issues:"])
            for detail in qa_design_details[:8]:
                refs = " | ".join(str(ref) for ref in (detail.get("refs") or [])[:3])
                lines.append(
                    f"- {detail.get('key','')} {detail.get('status','')} {detail.get('summary','')} "
                    f"[{detail.get('fetch_status','')}] {refs}"
                )
        for item in evidence[:5]:
            snippet = (item.get("evidence") or item.get("text") or "").replace("\n", " ")[:220]
            lines.append(f"- {item.get('doc_path','')} :: {item.get('locator','')} :: {snippet}")
        qa_cases = issue.get("qa_cases") or []
        if qa_cases:
            lines.extend(["", "Top QA Cases:"])
            for case in qa_cases[:5]:
                lines.append(
                    f"- {case.get('kind','')} {case.get('priority','')} {case.get('feature_point','')} :: {case.get('test_point','')} "
                    f"({case.get('doc_path','')} {case.get('locator','')})"
                )
        lines.extend(["", "Description:", str(issue.get("description", ""))[:3000]])
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(lines))
        self.detail_text.configure(state=tk.DISABLED)

    def refresh_evidence_table(self, issue: dict[str, Any]) -> None:
        self.evidence_tree.delete(*self.evidence_tree.get_children())
        for idx, item in enumerate(issue.get("evidence") or []):
            iid = str(idx)
            qa_cases = item.get("qa_cases") or []
            self.evidence_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    item.get("match_score", ""),
                    item.get("audio_score", ""),
                    item.get("ready_state", ""),
                    item.get("sound_type", ""),
                    summarize_qa_cases(qa_cases),
                    summarize_qa_method(qa_cases),
                    item.get("qa_source", ""),
                    item.get("doc_path", ""),
                    item.get("locator", ""),
                ),
            )

    def current_evidence_item(self) -> dict[str, Any] | None:
        issues = self.selected_issues()
        if not issues:
            return None
        selected = self.evidence_tree.selection()
        if not selected:
            evidence = issues[0].get("evidence") or []
            return evidence[0] if evidence else None
        evidence = issues[0].get("evidence") or []
        idx = int(selected[0])
        return evidence[idx] if 0 <= idx < len(evidence) else None

    def open_selected_evidence(self) -> None:
        item = self.current_evidence_item()
        if not item:
            messagebox.showinfo("Open Evidence", "Select an issue with evidence first.")
            return
        full_path = item.get("full_path")
        if full_path and Path(full_path).exists():
            os.startfile(str(Path(full_path)))

    def selected_qa_cases(self) -> list[dict[str, Any]]:
        item = self.current_evidence_item()
        if item and item.get("qa_cases"):
            return list(item.get("qa_cases") or [])
        issues = self.selected_issues()
        if issues:
            return list(issues[0].get("qa_cases") or [])
        return []

    def format_qa_cases(self, cases: list[dict[str, Any]], limit: int = 80) -> str:
        if not cases:
            return "No QA cases matched the selected Jira/design evidence."
        lines = [summarize_qa_cases(cases, compact=False), ""]
        for index, case in enumerate(cases[:limit], 1):
            lines.append(f"{index}. {case.get('kind','')} {case.get('priority','')} [{case.get('status','')}]")
            lines.append(f"Feature: {case.get('feature_point','')}")
            lines.append(f"Test Point: {case.get('test_point','')}")
            steps = case.get("operation_steps") or []
            if steps:
                lines.append("Operation Steps:")
                for step_index, step in enumerate(steps, 1):
                    lines.append(f"  {step_index}. {step}")
            if case.get("expected_result"):
                lines.append(f"Expected Result: {case.get('expected_result','')}")
            refs = case.get("design_refs") or []
            if refs:
                lines.append("Design Refs: " + " | ".join(str(ref) for ref in refs[:5]))
            lines.append(f"Source: {case.get('doc_path','')} {case.get('locator','')} | Match: {case.get('qa_match_score','')} {case.get('qa_source','')}")
            lines.append("")
        if len(cases) > limit:
            lines.append(f"... {len(cases) - limit} more cases omitted.")
        return "\n".join(lines)

    def show_selected_qa_cases(self) -> None:
        cases = self.selected_qa_cases()
        if not cases:
            messagebox.showinfo("QA Cases", "No QA cases matched the selected row. Run Scan QA, then Match All Issues.")
            return
        win = tk.Toplevel(self)
        win.title("QA Cases")
        win.geometry("980x720")
        win.configure(bg=BG)
        text = tk.Text(win, bg="#101720", fg=INK, insertbackground=INK, relief=tk.FLAT, wrap=tk.WORD)
        scroll = ttk.Scrollbar(win, orient=tk.VERTICAL, command=text.yview)
        text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        win.rowconfigure(0, weight=1)
        win.columnconfigure(0, weight=1)
        text.configure(yscrollcommand=scroll.set)
        text.insert(tk.END, self.format_qa_cases(cases))
        text.configure(state=tk.DISABLED)

    def resolve_selected_issue_qa_refs(self, issue: dict[str, Any]) -> None:
        if issue.get("_qa_details_resolved") or not issue.get("qa_design_issues"):
            return
        self.status_var.set("Resolving QA test-case-design link for selected Jira issue...")
        self.update_idletasks()
        self.enrich_issue_with_qa_design_refs(issue, fetch_details=True, max_details=3)
        self.attach_qa_to_issue(issue)
        self.update_selected_qa_path_label(issue)
        self.show_issue_detail(issue)
        self.refresh_evidence_table(issue)

    def infer_selected_issue_qa_path(self, issue: dict[str, Any]) -> None:
        if not self.qa_index:
            return
        self.status_var.set("Inferring QA path from matched design topic...")
        self.update_idletasks()
        self.attach_qa_to_issue(issue)
        self.update_selected_qa_path_label(issue)
        self.show_issue_detail(issue)
        self.refresh_evidence_table(issue)
        self.save_jira_cache_now("Inferred QA path")

    def open_selected_qa_file(self) -> None:
        selected = self.selected_issues()
        issue = selected[0] if selected else None
        cases = self.selected_qa_cases()
        refs = list(issue.get("qa_doc_refs") or []) if issue else []
        design_root = Path(self.design_root_var.get().strip() or DEFAULT_DESIGN_ROOT)
        target = ""
        if issue:
            target = str(issue.get("qa_open_target") or "").strip()
        if not target:
            target = first_qa_open_target(cases, refs, design_root)
        if not target and issue and issue.get("qa_design_issues") and not issue.get("_qa_details_resolved"):
            try:
                self.resolve_selected_issue_qa_refs(issue)
                cases = self.selected_qa_cases()
                refs = list(issue.get("qa_doc_refs") or [])
                target = str(issue.get("qa_open_target") or "").strip() or first_qa_open_target(cases, refs, design_root)
            except Exception as exc:
                messagebox.showerror("Open QA Path", f"Could not resolve QA test-case-design issue:\n{exc}"[:4000])
                return
        if not target and issue and self.qa_index:
            try:
                self.infer_selected_issue_qa_path(issue)
                cases = self.selected_qa_cases()
                refs = list(issue.get("qa_doc_refs") or [])
                target = str(issue.get("qa_open_target") or "").strip() or first_qa_open_target(cases, refs, design_root)
            except Exception as exc:
                messagebox.showerror("Open QA Path", f"Could not infer QA path:\n{exc}"[:4000])
                return
        if not target:
            messagebox.showinfo("Open QA Path", "No QA path is available for the selected row. Run Scan QA and Sync Jira so the test case design issue can be read.")
            return
        try:
            path = Path(target)
            if path.exists():
                os.startfile(str(path))
                self.status_var.set(f"Opened QA file: {path}")
            else:
                os.startfile(target)
                self.status_var.set(f"Opened QA path: {target}")
        except Exception as exc:
            messagebox.showerror("Open QA Path", f"Could not open QA path:\n{target}\n\n{exc}"[:4000])

    def copy_jira_reply(self) -> None:
        issues = self.selected_issues()
        if not issues:
            messagebox.showinfo("Copy", "Select an issue first.")
            return
        text = self.jira_reply_text(issues[0])
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("Copied Jira reply draft.")

    def jira_reply_text(self, issue: dict[str, Any]) -> str:
        evidence = issue.get("evidence") or []
        lines = [
            f"Audio triage for {issue.get('key','')}: {issue.get('audio_required','Unknown')}",
            f"Can start: {issue.get('can_start','Unknown')} | Ready state: {issue.get('ready_state','Unknown')} | Confidence: {issue.get('confidence','Low')}",
            f"System: {issue.get('system','Unknown')} | Design area: {issue.get('design_area',UNMATCHED_DESIGN_LABEL)} | Version: {issue.get('version_label','Unspecified')}",
            f"Reason: {issue.get('reason','')}",
        ]
        if evidence:
            lines.append("Design evidence:")
            for item in evidence[:3]:
                snippet = (item.get("evidence") or item.get("text") or "").replace("\n", " ")[:220]
                lines.append(f"- {item.get('doc_path','')} ({item.get('locator','')}): {snippet}")
        else:
            lines.append("No matching design evidence found in the current local index.")
        if issue.get("ready_state") not in {"Ready", "Cuttable"}:
            lines.append("Question: please confirm the gameplay trigger/timing and owner before audio production starts.")
        return "\n".join(lines)

    def export_report(self) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        csv_path = REPORT_DIR / f"ProjectEF_AudioRequirement_Jira_Triage_{stamp}.csv"
        md_path = REPORT_DIR / f"ProjectEF_AudioRequirement_Jira_Triage_{stamp}.md"
        fields = [
            "key",
            "summary",
            "audio_required",
            "can_start",
            "ready_state",
            "system",
            "design_area",
            "design_doc",
            "dependency_label",
            "version",
            "sound_type",
            "confidence",
            "status",
            "assignee",
            "reporter",
            "creator",
            "components",
            "labels",
            "issue_links",
            "issue_type",
            "priority",
            "qa_summary",
            "qa_link_status",
            "qa_path",
            "qa_doc_refs",
            "reason",
            "best_doc",
            "best_locator",
            "best_snippet",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for issue in self.issues:
                evidence = issue.get("evidence") or []
                best = evidence[0] if evidence else {}
                writer.writerow({
                    "key": issue.get("key", ""),
                    "summary": issue.get("summary", ""),
                    "audio_required": issue.get("audio_required", ""),
                    "can_start": issue.get("can_start", ""),
                    "ready_state": issue.get("ready_state", ""),
                    "system": issue.get("system", ""),
                    "design_area": issue.get("design_area", ""),
                    "design_doc": issue.get("design_doc", ""),
                    "dependency_label": issue.get("dependency_label", ""),
                    "version": issue.get("version_label", ""),
                    "sound_type": issue.get("sound_type", ""),
                    "confidence": issue.get("confidence", ""),
                    "status": issue.get("status", ""),
                    "assignee": issue.get("assignee", ""),
                    "reporter": issue.get("reporter", ""),
                    "creator": issue.get("creator", ""),
                    "components": issue.get("components", ""),
                    "labels": issue.get("labels", ""),
                    "issue_links": issue.get("issue_links", ""),
                    "issue_type": issue.get("issue_type", ""),
                    "priority": issue.get("priority", ""),
                    "qa_summary": issue.get("qa_summary", ""),
                    "qa_link_status": issue.get("qa_link_status", ""),
                    "qa_path": issue.get("qa_path", ""),
                    "qa_doc_refs": "; ".join(str(ref) for ref in issue.get("qa_doc_refs") or []),
                    "reason": issue.get("reason", ""),
                    "best_doc": best.get("doc_path", ""),
                    "best_locator": best.get("locator", ""),
                    "best_snippet": (best.get("evidence") or best.get("text") or "")[:300],
                })
        lines = [
            "# ProjectEF Audio Requirement Jira Triage",
            "",
            f"- Generated: {now_stamp()}",
            f"- Design root: `{self.design_root_var.get().strip()}`",
            f"- Index: `{INDEX_PATH}`",
            f"- Issues: {len(self.issues)}",
            "",
            "| Jira | Audio? | Start? | Ready | System | Version | Design | Dependency | QA Link | QA Path | Confidence | Summary | Best Evidence |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for issue in self.issues:
            evidence = issue.get("evidence") or []
            best = evidence[0] if evidence else {}
            best_label = f"{best.get('doc_path','')} {best.get('locator','')}".strip()
            lines.append(
                "| "
                + " | ".join(
                    sanitize_md(str(value))
                    for value in [
                        issue.get("key", ""),
                        issue.get("audio_required", ""),
                        issue.get("can_start", ""),
                        issue.get("ready_state", ""),
                        issue.get("system", ""),
                        issue.get("version_label", ""),
                        issue.get("design_area", ""),
                        issue.get("dependency_label", ""),
                        issue.get("qa_link_status", ""),
                        issue.get("qa_path", ""),
                        issue.get("confidence", ""),
                        issue.get("summary", ""),
                        best_label,
                    ]
                )
                + " |"
            )
        lines.append("\n## Details\n")
        for issue in self.issues:
            lines.append(f"### {issue.get('key','')} {issue.get('summary','')}")
            lines.append(f"- Audio Required: {issue.get('audio_required','')}")
            lines.append(f"- Can Start: {issue.get('can_start','')}")
            lines.append(f"- Ready State: {issue.get('ready_state','')}")
            lines.append(f"- System: {issue.get('system','')} | Design Area: {issue.get('design_area','')} | Design Doc: {issue.get('design_doc','')} | Version: {issue.get('version_label','')}")
            lines.append(f"- Dependency: {issue.get('dependency_label','')} | Links: {issue.get('issue_links','')}")
            lines.append(f"- Jira Status: {issue.get('status','')} | Assignee: {issue.get('assignee','')} | Reporter: {issue.get('reporter','')} | Creator: {issue.get('creator','')}")
            lines.append(f"- Component: {issue.get('components','')} | Labels: {issue.get('labels','')}")
            lines.append(f"- QA: {issue.get('qa_summary','No QA')} | {issue.get('qa_link_status','')} | `{issue.get('qa_path','')}`")
            lines.append(f"- Reason: {issue.get('reason','')}")
            for item in (issue.get("evidence") or [])[:5]:
                snippet = (item.get("evidence") or item.get("text") or "").replace("\n", " ")[:300]
                lines.append(f"- Evidence: `{item.get('doc_path','')}` {item.get('locator','')} - QA {summarize_qa_cases(item.get('qa_cases') or [])} - {snippet}")
            for case in (issue.get("qa_cases") or [])[:5]:
                lines.append(f"- QA Case: `{case.get('doc_path','')}` {case.get('locator','')} - {case.get('feature_point','')} / {case.get('test_point','')}")
            lines.append("")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        self.status_var.set(f"Exported: {md_path}")
        messagebox.showinfo("Export Report", f"{md_path}\n{csv_path}")

    def test_local_ai(self) -> None:
        url = self.ollama_url_var.get().strip().rstrip("/") or DEFAULT_OLLAMA_URL
        try:
            with urllib.request.urlopen(f"{url}/api/tags", timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            messagebox.showerror("Local AI", f"Ollama unavailable at {url}\n\n{exc}")
            return
        models = [item.get("name", "") for item in data.get("models", [])]
        messagebox.showinfo("Local AI", "Ollama OK.\n\n" + "\n".join(models))

    def local_ai_selected(self) -> None:
        selected = self.selected_issues()
        if not selected:
            messagebox.showinfo("Local AI", "Select issues first.")
            return
        for issue in selected:
            try:
                result = self.local_ai_review(issue)
                issue["audio_required"] = result.get("audio_required", issue.get("audio_required", "Unknown"))
                issue["ready_state"] = result.get("ready_state", issue.get("ready_state", "Unknown"))
                issue["confidence"] = result.get("confidence", issue.get("confidence", "Low"))
                issue["reason"] = "Local AI: " + result.get("reason", issue.get("reason", ""))
                if result.get("question"):
                    issue["question"] = result["question"]
                assign_issue_dimensions(issue)
            except Exception as exc:
                messagebox.showerror("Local AI", str(exc)[:4000])
                break
        self.refresh_filter_options()
        self.refresh_issue_table()
        self.on_issue_selected()

    def local_ai_review(self, issue: dict[str, Any]) -> dict[str, Any]:
        url = self.ollama_url_var.get().strip().rstrip("/") or DEFAULT_OLLAMA_URL
        model = self.local_model_var.get().strip() or DEFAULT_LOCAL_MODEL
        evidence_lines = []
        for item in (issue.get("evidence") or [])[:5]:
            snippet = (item.get("evidence") or item.get("text") or "").replace("\n", " ")[:500]
            evidence_lines.append(f"{item.get('doc_path','')} {item.get('locator','')}: {snippet}")
        prompt = (
            "You are a conservative game-audio production triage assistant.\n"
            "Decide whether the Jira issue needs audio work, and whether it is ready.\n"
            "Use only the Jira text and provided design evidence. If evidence is weak, use Unknown or Maybe.\n"
            "Return strict JSON only with keys: audio_required, ready_state, confidence, reason, question.\n"
            "Allowed audio_required: Yes, Maybe, No, Unknown.\n"
            "Allowed ready_state: Ready, DesignOnly, Blocked, Risky, Cuttable, UnknownNeedsDesign.\n\n"
            f"Jira: {issue.get('key','')}\n"
            f"Summary: {issue.get('summary','')}\n"
            f"Description: {str(issue.get('description',''))[:2500]}\n\n"
            "Design evidence:\n" + "\n".join(evidence_lines)
        )
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 700},
        }
        request = urllib.request.Request(
            f"{url}/api/generate",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        return extract_json(data.get("response", ""))


def sanitize_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")[:400]


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def self_test() -> int:
    root = DEFAULT_DESIGN_ROOT
    if not root.exists():
        print(json.dumps({"root": str(root), "exists": False}, ensure_ascii=False, indent=2))
        return 1
    index = build_design_index(root, limit=25)
    issue = issue_from_manual_text("SELF-TEST", "\u9e1f\u98de\u884c\u52a8\u753b\u7fc5\u8180\u97f3\u6548\u9700\u8981\u914d\u7f6e")
    evidence = rank_evidence(issue, index, limit=5)
    verdict = classify_issue(issue, evidence)
    print(json.dumps({"summary": index["summary"], "verdict": verdict, "evidence_count": len(evidence)}, ensure_ascii=False, indent=2))
    return 0


def self_test_qa() -> int:
    root = DEFAULT_DESIGN_ROOT
    if not root.exists():
        print(json.dumps({"root": str(root), "exists": False}, ensure_ascii=False, indent=2))
        return 1
    index = build_qa_acceptance_index(root)
    save_qa_index(index)
    sample = index.get("cases", [])[:5]
    print(json.dumps({"summary": index.get("summary", {}), "sample_cases": sample}, ensure_ascii=False, indent=2))
    return 0


def arg_value(name: str, default: str = "") -> str:
    if name not in sys.argv:
        return default
    index = sys.argv.index(name)
    if index + 1 >= len(sys.argv):
        return default
    return sys.argv[index + 1]


def scan_diff_once_cli() -> int:
    design_root_text = arg_value("--design-root", str(DEFAULT_DESIGN_ROOT))
    root = Path(design_root_text)
    if not root.exists():
        print(json.dumps({"ok": False, "error": f"Design root not found: {root}"}, ensure_ascii=False, indent=2))
        return 1

    previous = load_index()
    index = build_design_index(root, previous_index=previous)
    ensure_design_index_lookup(index)
    save_index(index)
    snapshot_path = save_snapshot(index)

    if previous:
        diff = diff_indexes(previous, index)
    else:
        diff = {
            "version": 1,
            "generated_at": now_stamp(),
            "old_generated_at": "",
            "new_generated_at": index.get("generated_at", ""),
            "design_root": str(root),
            "summary": {
                "baseline_created": True,
                "message": "No previous index existed; current scan was saved as baseline.",
            },
            "added_docs": [],
            "removed_docs": [],
            "modified_docs": [],
            "new_audio_candidates": [],
            "removed_audio_candidates": [],
        }

    report_paths = write_diff_reports(diff)
    output = {
        "ok": True,
        "index": str(INDEX_PATH),
        "snapshot": str(snapshot_path),
        "summary": index.get("summary", {}),
        "diff_summary": diff.get("summary", {}),
        "reports": report_paths,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def scan_qa_once_cli() -> int:
    design_root_text = arg_value("--design-root", str(DEFAULT_DESIGN_ROOT))
    root = Path(design_root_text)
    if not root.exists():
        print(json.dumps({"ok": False, "error": f"Design root not found: {root}"}, ensure_ascii=False, indent=2))
        return 1
    index = build_qa_acceptance_index(root)
    save_qa_index(index)
    output = {
        "ok": True,
        "qa_index": str(QA_INDEX_PATH),
        "summary": index.get("summary", {}),
        "generated_roots": index.get("generated_roots", []),
        "testcase_roots": index.get("testcase_roots", []),
        "scan_roots": index.get("scan_roots", []),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--self-test-qa" in sys.argv:
        return self_test_qa()
    if "--scan-qa-once" in sys.argv:
        return scan_qa_once_cli()
    if "--scan-diff-once" in sys.argv:
        return scan_diff_once_cli()
    app = TriageGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
