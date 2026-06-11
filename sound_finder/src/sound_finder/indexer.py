from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable

from .audio_meta import read_duration_seconds
from .db import PlanCategory, SoundFinderDB


AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".aif",
    ".aiff",
    ".m4a",
    ".wma",
}


def iter_audio_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name.lower() not in {".git", ".svn", "__pycache__", "cache", "temp", "__macosx"}
        ]
        for filename in filenames:
            if filename.startswith("._"):
                continue
            path = Path(dirpath) / filename
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                yield path


def scan_library(
    db: SoundFinderDB,
    root: Path,
    progress: Callable[[dict[str, int], str], None] | None = None,
    *,
    mode: str = "incremental",
) -> dict[str, int]:
    if mode not in {"incremental", "rebuild"}:
        raise ValueError(f"未知扫描模式：{mode}")

    root = root.resolve()
    removed = db.delete_audio_files_in_library(root) if mode == "rebuild" else 0
    indexed = {} if mode == "rebuild" else db.audio_file_fingerprints(root)
    stats = {
        "seen": 0,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "removed": removed,
    }

    for path in iter_audio_files(root):
        stats["seen"] += 1
        try:
            stat = path.stat()
        except OSError:
            stats["errors"] += 1
            continue

        path_text = str(path)
        previous = indexed.get(path_text)
        if previous and previous[0] == stat.st_size and abs(previous[1] - stat.st_mtime) < 0.0001:
            stats["skipped"] += 1
            if stats["seen"] % 500 == 0 and progress:
                progress(dict(stats), path_text)
            continue

        duration = read_duration_seconds(path)
        db.upsert_audio_file(
            path=path,
            duration=duration,
            size=stat.st_size,
            modified=stat.st_mtime,
        )
        if previous:
            stats["updated"] += 1
        else:
            stats["added"] += 1

        processed = stats["added"] + stats["updated"]
        if processed % 50 == 0:
            db.commit()
            if progress:
                progress(dict(stats), path_text)

    db.commit()
    if progress:
        progress(dict(stats), "扫描完成")
    return stats


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[_\\/\-.()\[\]{}]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokens_for(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", normalize_text(text)) if token}


def score_file(file_row: dict, keywords: list[str]) -> tuple[float, list[str]]:
    name = normalize_text(file_row["name"])
    folder = normalize_text(file_row["folder"])
    full_text = f"{name} {folder} {file_row['extension']}"
    token_set = tokens_for(full_text)

    score = 0.0
    matched: list[str] = []
    for raw_term in keywords:
        term = normalize_text(raw_term)
        if not term:
            continue

        term_tokens = tokens_for(term)
        term_score = 0.0

        if term in name:
            term_score += 70.0
        elif term in full_text:
            term_score += 45.0

        token_hits = term_tokens & token_set
        if token_hits:
            term_score += len(token_hits) * 18.0
            if token_hits == term_tokens and len(term_tokens) > 1:
                term_score += 12.0

        partial_hits = 0
        for token in term_tokens:
            if len(token) >= 4 and any(token in target for target in token_set):
                partial_hits += 1
        term_score += partial_hits * 5.0

        if term_score > 0:
            matched.append(raw_term)
            score += term_score

    if matched:
        shorter_bonus = max(0.0, 8.0 - len(name) / 20.0)
        score += shorter_bonus

    return score, matched


def style_penalty(file_row: dict, category: PlanCategory, keywords: list[str]) -> float:
    text = f"{file_row['name']} {file_row['folder']}".lower()
    requested = " ".join(keywords).lower()
    style = (category.recipe_style or "").lower()

    if any(term in requested for term in ["8bit", "8 bit", "retro", "arcade", "pixel", "chiptune"]):
        return 1.0

    hard_unwanted = ["8bit", "8 bit", "chiptune", "arcade", "gameboy", "nes", "pixel"]
    soft_unwanted = ["retro", "square", "synth"]
    ui_beep_unwanted = ["bleep", "blip"]
    digital_unwanted = ["digital"]

    if any(term in text for term in hard_unwanted):
        return 0.18
    if any(term in text for term in soft_unwanted):
        return 0.38
    if any(term in text for term in ui_beep_unwanted) and not any(term in requested for term in ui_beep_unwanted):
        return 0.5
    if "realistic" in style or "tactile" in style or "warm" in style or "mechanical" in style:
        if any(term in text for term in digital_unwanted):
            return 0.62
    return 1.0


def search_audio_files(
    db: SoundFinderDB,
    plan: list[PlanCategory],
    limit_per_category: int = 200,
) -> dict[int, list[dict]]:
    library_root = db.get_setting("library_root", "")
    results_by_index: dict[int, list[dict]] = {}

    for index, category in enumerate(plan):
        if not category.include:
            results_by_index[index] = []
            continue

        keywords = list(category.keywords)
        for layer in category.recipe:
            keywords.extend(layer.get("keywords", []))
        seen_keywords: set[str] = set()
        keywords = [
            keyword
            for keyword in keywords
            if keyword.strip() and not (keyword.strip().lower() in seen_keywords or seen_keywords.add(keyword.strip().lower()))
        ]

        candidate_limit = 20000
        if getattr(db, "audio_fts_ready", lambda: False)():
            candidate_limit = max(2000, limit_per_category * 50)
        files = db.candidate_audio_files(keywords, library_root, limit=candidate_limit)
        scored: list[dict] = []
        for file_row in files:
            score, matched = score_file(file_row, keywords)
            if score <= 0:
                continue
            score *= style_penalty(file_row, category, keywords)
            if score <= 0:
                continue
            item = dict(file_row)
            item["audio_file_id"] = item["id"]
            item["score"] = round(score, 2)
            item["matched_terms"] = matched
            scored.append(item)

        # Rank by how many distinct requested keywords a file hits FIRST, then score.
        # Without this, files matching a single generic token (e.g. just "wood" or
        # "light") flood the top and every category fills its cap with weak matches.
        scored.sort(key=lambda row: (-len(row.get("matched_terms", [])), -row["score"], row["name"].lower()))
        results_by_index[index] = scored[:limit_per_category]

    return results_by_index
