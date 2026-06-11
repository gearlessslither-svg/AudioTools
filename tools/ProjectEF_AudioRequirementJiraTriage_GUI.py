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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any
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
CONFIG_PATH = APP_DIR / "audio_requirement_jira_triage_config.json"
SNAPSHOT_DIR = APP_DIR / "audio_requirement_snapshots"
LATEST_DIFF_PATH = APP_DIR / "audio_requirement_design_diff_latest.json"
DEDICATED_JIRA_PROFILE_DIR = APP_DIR / "jira_browser_profile"
JIRA_CDP_PORT = 9233

DEFAULT_DESIGN_ROOT = Path(r"D:\EF New\Design")
DEFAULT_JIRA_URL = "http://ef.jira.blackjack-local.com:8080"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL = "qwen2.5:7b-instruct"
INDEX_VERSION = 1
JIRA_SEARCH_FIELDS = "summary,description,status,assignee,reporter,creator,updated,fixVersions,versions,components,labels,issuetype,priority,project,issuelinks"

TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".html", ".htm"}
TABLE_EXTENSIONS = {".xlsx"}
DOC_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | TABLE_EXTENSIONS | DOC_EXTENSIONS | PDF_EXTENSIONS
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


def build_design_index(root: Path, progress=None, limit: int = 0) -> dict[str, Any]:
    root = root.resolve()
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not should_skip(path)
    ]
    files.sort(key=lambda item: normalize_path(item).lower())
    if limit:
        files = files[:limit]

    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for file_index, path in enumerate(files, 1):
        if progress:
            progress(f"Scanning {file_index}/{len(files)}: {path.name}")
        try:
            stat = path.stat()
            rel = normalize_path(path.relative_to(root))
            doc_hash = file_hash(path)
            documents.append({
                "path": rel,
                "full_path": str(path),
                "extension": path.suffix.lower(),
                "mtime": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "size": stat.st_size,
                "sha1": doc_hash,
            })
            file_chunks = chunks_from_file(path, root)
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
                req_id = f"AR-{len(requirements) + 1:05d}"
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
        },
    }


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
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def save_snapshot(index: dict[str, Any]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = SNAPSHOT_DIR / f"audio_requirement_index_{stamp}.json"
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
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
            config.update({k: str(v) for k, v in loaded.items() if k in config})
    except Exception:
        pass
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def match_score(query_tokens: set[str], record: dict[str, Any]) -> float:
    tokens = set(record.get("tokens") or [])
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
    candidates: list[dict[str, Any]] = []
    for source_name in ("requirements", "chunks"):
        for record in index.get(source_name, []):
            score = match_score(q_tokens, record)
            if score <= 0:
                continue
            item = dict(record)
            item["match_score"] = score
            item["source"] = source_name
            candidates.append(item)
    candidates.sort(key=lambda item: (item["match_score"], item.get("audio_score", 0)), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in candidates:
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


def issue_link_labels(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    labels: list[str] = []
    for link in values:
        if not isinstance(link, dict):
            continue
        link_type = ""
        if isinstance(link.get("type"), dict):
            link_type = str(link["type"].get("name") or link["type"].get("outward") or link["type"].get("inward") or "").strip()
        linked = link.get("outwardIssue") or link.get("inwardIssue")
        if not isinstance(linked, dict):
            continue
        key = str(linked.get("key") or "").strip()
        fields = linked.get("fields") if isinstance(linked.get("fields"), dict) else {}
        status = ""
        if isinstance(fields.get("status"), dict):
            status = str(fields["status"].get("name") or "").strip()
        label = " ".join(part for part in (link_type, key, status) if part)
        if label:
            labels.append(label)
    return "; ".join(labels)


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
        return "NoEvidence"
    parts = [part for part in re.split(r"[\\/]+", doc_path) if part]
    if not parts:
        return "NoEvidence"
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
    DEDICATED_JIRA_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    edge = find_edge_executable()
    url = jira_issue_navigator_url(base_url, jql)
    args = [
        edge,
        f"--user-data-dir={DEDICATED_JIRA_PROFILE_DIR}",
        f"--remote-debugging-port={JIRA_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
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
        self.detail_visible_var = tk.BooleanVar(value=False)

        self.index: dict[str, Any] = {}
        self.latest_diff: dict[str, Any] = {}
        self.issues: list[dict[str, Any]] = []
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
        self.button(design_panel, "Scan + Diff Changes", self.scan_diff_async, bg="#8867d8").pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Compare Latest", self.compare_latest_snapshots).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Load Index", self.load_index_clicked).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open Diff", self.open_latest_diff).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open Index", lambda: os.startfile(str(INDEX_PATH)) if INDEX_PATH.exists() else None).pack(side=tk.LEFT, padx=4)
        self.button(design_panel, "Open Reports", lambda: os.startfile(str(REPORT_DIR))).pack(side=tk.LEFT, padx=4)

        jira_panel = self.panel(self)
        jira_panel.pack(fill=tk.X, padx=16, pady=(0, 8))
        self.entry(jira_panel, "Jira URL", self.jira_url_var, 300).pack(side=tk.LEFT, padx=(10, 8), pady=10)
        self.entry(jira_panel, "Cookie optional", self.jira_cookie_var, 300, show="*").pack(side=tk.LEFT, padx=8, pady=10)
        self.entry(jira_panel, "Issue Key", self.issue_key_var, 120).pack(side=tk.LEFT, padx=8, pady=10)
        self.button(jira_panel, "Test Jira", self.test_jira).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Open Dedicated Jira", self.open_dedicated_jira_browser_clicked, bg="#315577").pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Use Browser Login", self.use_browser_login_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Close Edge + Login", self.close_edge_then_login_clicked, bg="#8d5f32").pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Sync Issue", self.sync_issue_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Import Jira CSV", self.import_jira_csv_clicked).pack(side=tk.LEFT, padx=4)
        self.button(jira_panel, "Paste Jira Text", self.paste_jira_text).pack(side=tk.LEFT, padx=4)

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
        columns = ("key", "required", "start", "ready", "system", "version", "design", "dependency", "confidence", "status", "summary", "evidence")
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

        bottom = tk.Frame(paned, bg=BG)
        paned.add(bottom, minsize=220, height=300)
        bottom_header = tk.Frame(bottom, bg=BG)
        bottom_header.pack(fill=tk.X, pady=(0, 6))
        tk.Label(bottom_header, textvariable=self.selected_summary_var, bg=BG, fg=MUTED, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.detail_toggle_button = self.button(bottom_header, "Show Details", self.toggle_detail_panel)
        self.detail_toggle_button.pack(side=tk.RIGHT, padx=(8, 0))

        self.detail_frame = tk.Frame(bottom, bg=BG)
        self.detail_text = tk.Text(self.detail_frame, height=7, bg="#101720", fg=INK, insertbackground=INK, relief=tk.FLAT, wrap=tk.WORD)
        detail_y = ttk.Scrollbar(self.detail_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_y.grid(row=0, column=1, sticky="ns")
        self.detail_frame.rowconfigure(0, weight=1)
        self.detail_frame.columnconfigure(0, weight=1)
        self.detail_text.configure(yscrollcommand=detail_y.set)
        self.detail_text.configure(state=tk.DISABLED)

        ev_columns = ("score", "audio", "ready", "type", "path", "locator")
        self.evidence_frame = tk.Frame(bottom, bg=BG)
        self.evidence_frame.pack(fill=tk.BOTH, expand=True)
        self.evidence_tree = ttk.Treeview(self.evidence_frame, columns=ev_columns, show="headings", selectmode="browse")
        ev_headings = {"score": "Match", "audio": "Audio", "ready": "Ready", "type": "Type", "path": "Doc", "locator": "Where"}
        ev_widths = {"score": 70, "audio": 70, "ready": 110, "type": 110, "path": 450, "locator": 170}
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
            "ollama_url": self.ollama_url_var.get().strip(),
            "local_model": self.local_model_var.get().strip(),
        })

    def try_load_index_silent(self) -> None:
        if INDEX_PATH.exists():
            try:
                self.index = load_index()
                self.update_summary()
                self.status_var.set(f"Loaded existing index: {INDEX_PATH}")
            except Exception:
                pass

    def load_index_clicked(self) -> None:
        try:
            self.index = load_index()
        except Exception as exc:
            messagebox.showerror("Load Index", str(exc))
            return
        self.update_summary()
        messagebox.showinfo("Load Index", f"Loaded {len(self.index.get('requirements', []))} audio candidates.")

    def show_quick_start(self) -> None:
        messagebox.showinfo(
            "How To Use",
            "\n".join([
                "1. The design index is already loaded when the top-right summary shows Index docs/chunks/requirements.",
                "2. Click Open Dedicated Jira. Log into Jira once in that separate Edge window.",
                "3. Click One Click Refresh Jira. The tool will reuse the dedicated Jira browser session.",
                "4. Keep or edit the JQL, for example: assignee = yupeng AND statusCategory != Done ORDER BY updated DESC",
                "5. Sync JQL uses the optional Cookie field. One Click Refresh Jira uses the dedicated browser first.",
                "6. If browser sync is blocked by local policy, export CSV from Jira, then click Import Jira CSV.",
                "7. Match All Issues only classifies issues that are already loaded.",
                "8. If Jira auth is unavailable, paste one issue into Manual Jira text / notes, then click Paste Jira Text.",
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
        while fetched < limit:
            params = urllib.parse.urlencode({
                "jql": jql,
                "startAt": str(start_at),
                "maxResults": str(min(page_size, limit - fetched)),
                "fields": JIRA_SEARCH_FIELDS,
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
                self.add_or_replace_issue(issue, refresh=False)
            fetched += len(raw_issues)
            start_at += len(raw_issues)
            self.status_var.set(f"Synced Jira from dedicated browser {fetched}/{total if total is not None else '?'}...")
            self.update_idletasks()
            if start_at >= total:
                break
        self.match_all_issues()
        self.status_var.set(f"Synced and matched {fetched} Jira issues via dedicated browser. Total matched in table: {len(self.issues)}")
        return True

    def one_click_refresh_jira_clicked(self) -> None:
        if not self.index and INDEX_PATH.exists():
            try:
                self.index = load_index()
                self.update_summary()
            except Exception as exc:
                messagebox.showerror("One Click Refresh Jira", f"Failed to load design index:\n{exc}")
                return
        if not self.index:
            messagebox.showinfo("One Click Refresh Jira", "Load or scan the design index first.")
            return

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

    def start_design_scan(self, with_diff: bool) -> None:
        root = Path(self.design_root_var.get().strip())
        if not root.exists():
            messagebox.showerror("Scan Design", f"Design root not found:\n{root}")
            return
        self.save_current_config()
        self.status_var.set("Scanning design docs..." + (" Then comparing changes." if with_diff else ""))
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
            index = build_design_index(root, progress=lambda msg: self.after(0, self.status_var.set, msg))
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
            self.status_var.set(f"Scan complete. Requirements: {summary.get('requirements', 0)} Chunks: {summary.get('chunks', 0)}")
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
        start_counts = Counter(issue.get("can_start", "Unknown") for issue in self.issues)
        start_bits = " ".join(f"{key}:{value}" for key, value in start_counts.items() if value)
        self.summary_var.set(
            f"Index docs:{summary.get('files_scanned', 0)} chunks:{summary.get('chunks', 0)} "
            f"requirements:{summary.get('requirements', 0)} issues:{len(self.issues)} {start_bits}"
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
        self.match_all_issues()

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
            self.match_all_issues()
        else:
            self.refresh_filter_options()
            self.refresh_issue_table()
            self.update_summary()
        self.status_var.set(f"Imported {count} Jira issues from CSV: {path}")
        messagebox.showinfo("Import Jira CSV", f"Imported {count} Jira issues.\n\n{path}")

    def fetch_issue(self, key: str) -> dict[str, Any]:
        base = self.jira_url_var.get().strip()
        cookie = self.jira_cookie_var.get().strip()
        status, ctype, body = jira_request(base, f"/rest/api/2/issue/{urllib.parse.quote(key)}", cookie, timeout=20)
        if status == 200 and "json" in ctype.lower():
            data = json.loads(body)
            issue = parse_issue_from_json(data)
            issue["url"] = f"{base.rstrip()}/browse/{key}"
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
        fields = urllib.parse.quote(JIRA_SEARCH_FIELDS, safe=",")
        response = cdp_fetch_jira_url(base, self.jql_var.get().strip(), f"/rest/api/2/issue/{urllib.parse.quote(key)}?fields={fields}", timeout=60)
        status = int(response.get("status") or 0)
        ctype = str(response.get("contentType") or "")
        body = str(response.get("text") or "")
        if status == 200 and "json" in ctype.lower():
            issue = parse_issue_from_json(json.loads(body))
            issue["url"] = f"{base.rstrip()}/browse/{key}"
            issue["source"] = "Jira REST via dedicated browser"
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
        while fetched < limit:
            params = urllib.parse.urlencode({
                "jql": jql,
                "startAt": str(start_at),
                "maxResults": str(min(page_size, limit - fetched)),
                "fields": JIRA_SEARCH_FIELDS,
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
                self.add_or_replace_issue(issue, refresh=False)
            fetched += len(raw_issues)
            start_at += len(raw_issues)
            self.status_var.set(f"Synced Jira {fetched}/{total if total is not None else '?'}...")
            self.update_idletasks()
            if start_at >= total:
                break
        self.match_all_issues()
        self.status_var.set(f"Synced and matched {fetched} Jira issues. Total matched in table: {len(self.issues)}")

    def paste_jira_text(self) -> None:
        text = self.manual_text.get("1.0", tk.END).strip()
        if not text:
            text = simpledialog.askstring("Paste Jira Text", "Paste summary/description text:", parent=self) or ""
        if not text.strip():
            return
        key = self.issue_key_var.get().strip().upper() or f"MANUAL-{len(self.issues) + 1}"
        issue = issue_from_manual_text(key, text)
        self.add_or_replace_issue(issue)
        self.match_all_issues()

    def add_or_replace_issue(self, issue: dict[str, Any], refresh: bool = True) -> None:
        issue["id"] = issue.get("key") or f"ISSUE-{len(self.issues) + 1}"
        issue["version_label"] = issue_version_label(issue)
        issue.setdefault("can_start", "Unknown")
        issue.setdefault("system", "")
        issue.setdefault("design_area", "NoEvidence")
        issue.setdefault("design_doc", "")
        issue.setdefault("dependency_label", dependency_label(issue))
        issue.setdefault("audio_required", "Unknown")
        issue.setdefault("ready_state", "Unknown")
        issue.setdefault("sound_type", "")
        issue.setdefault("issue_links", "")
        issue.setdefault("reporter", "")
        issue.setdefault("creator", "")
        for idx, existing in enumerate(self.issues):
            if existing.get("id") == issue["id"]:
                self.issues[idx] = issue
                break
        else:
            self.issues.append(issue)
        if refresh:
            self.refresh_filter_options()
            self.refresh_issue_table()
            self.update_summary()

    def match_all_issues(self) -> None:
        if not self.index:
            messagebox.showinfo("Match", "Load or scan the design index first.")
            return
        if not self.issues:
            messagebox.showinfo("Match", "No Jira issues loaded yet. Click Sync JQL first, or paste an issue into Manual Jira text / notes and click Paste Jira Text.")
            return
        for issue in self.issues:
            evidence = rank_evidence(issue, self.index, limit=12)
            verdict = classify_issue(issue, evidence)
            issue["evidence"] = evidence
            issue.update(verdict)
            assign_issue_dimensions(issue)
        self.refresh_filter_options()
        self.refresh_issue_table()
        self.update_summary()
        self.status_var.set(f"Matched {len(self.issues)} issues against design index.")

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
            f"Reason: {issue.get('reason','-')}",
            "",
            "Top Evidence:",
        ]
        for item in evidence[:5]:
            snippet = (item.get("evidence") or item.get("text") or "").replace("\n", " ")[:220]
            lines.append(f"- {item.get('doc_path','')} :: {item.get('locator','')} :: {snippet}")
        lines.extend(["", "Description:", str(issue.get("description", ""))[:3000]])
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(lines))
        self.detail_text.configure(state=tk.DISABLED)

    def refresh_evidence_table(self, issue: dict[str, Any]) -> None:
        self.evidence_tree.delete(*self.evidence_tree.get_children())
        for idx, item in enumerate(issue.get("evidence") or []):
            iid = str(idx)
            self.evidence_tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    item.get("match_score", ""),
                    item.get("audio_score", ""),
                    item.get("ready_state", ""),
                    item.get("sound_type", ""),
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
            f"System: {issue.get('system','Unknown')} | Design area: {issue.get('design_area','NoEvidence')} | Version: {issue.get('version_label','Unspecified')}",
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
            "| Jira | Audio? | Start? | Ready | System | Version | Design | Dependency | Confidence | Summary | Best Evidence |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
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
            lines.append(f"- Reason: {issue.get('reason','')}")
            for item in (issue.get("evidence") or [])[:5]:
                snippet = (item.get("evidence") or item.get("text") or "").replace("\n", " ")[:300]
                lines.append(f"- Evidence: `{item.get('doc_path','')}` {item.get('locator','')} - {snippet}")
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
    index = build_design_index(root)
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


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--scan-diff-once" in sys.argv:
        return scan_diff_once_cli()
    app = TriageGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
