from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .db import DB_PATH, PlanCategory, SoundFinderDB
from .indexer import search_audio_files


DEFAULT_BENCHMARK_QUERIES = [
    "water splash",
    "fish water",
    "food drink",
    "button click",
    "whoosh magic",
    "metal impact",
]


def database_status(db_path: Path = DB_PATH) -> str:
    if not db_path.exists():
        return f"Database not found: {db_path}"

    db = SoundFinderDB(db_path)
    con = db.conn
    lines = [
        "Sound Finder database status",
        f"path: {db_path}",
        f"size_mb: {db_path.stat().st_size / 1024 / 1024:.2f}",
        "",
        "tables:",
    ]

    table_rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for row in table_rows:
        name = row["name"]
        try:
            count = con.execute(f"SELECT COUNT(*) AS total FROM {name}").fetchone()["total"]
        except sqlite3.Error as exc:
            count = f"ERROR {exc}"
        lines.append(f"  {name}: {count}")

    lines.extend(["", "indexes:"])
    index_rows = con.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name"
    ).fetchall()
    for row in index_rows:
        lines.append(f"  {row['tbl_name']}: {row['name']}")

    lines.extend(["", "settings:"])
    setting_rows = con.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    for row in setting_rows:
        lines.append(f"  {row['key']}: {row['value']}")

    library_root = db.get_setting("library_root", "")
    if library_root:
        lines.append("")
        lines.append(f"library_audio_count: {db.count_audio_files(library_root)}")

    lines.extend(["", "fts:"])
    for key, value in db.audio_fts_status().items():
        lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def rebuild_fts(db_path: Path = DB_PATH) -> str:
    db = SoundFinderDB(db_path)
    start = time.perf_counter()
    result = db.rebuild_audio_files_fts()
    elapsed = time.perf_counter() - start
    return "\n".join(
        [
            "Sound Finder FTS rebuild complete",
            f"db: {db_path}",
            f"audio_count: {result['audio_count']}",
            f"rebuilt_at: {result['rebuilt_at']}",
            f"elapsed_seconds: {elapsed:.1f}",
        ]
    )


def benchmark_search(
    queries: list[str] | None = None,
    *,
    db_path: Path = DB_PATH,
    limit_per_category: int = 80,
) -> str:
    if queries is None:
        queries = DEFAULT_BENCHMARK_QUERIES

    db = SoundFinderDB(db_path)
    lines = [
        "Sound Finder search benchmark",
        f"db: {db_path}",
        f"limit_per_category: {limit_per_category}",
        "",
        "| query | ms | result_count | top_result |",
        "| --- | ---: | ---: | --- |",
    ]

    for query in queries:
        category = PlanCategory(
            name=query,
            direction=query,
            keywords=query.split(),
            recipe=[],
            recipe_style="realistic_tactile",
        )
        start = time.perf_counter()
        results = search_audio_files(db, [category], limit_per_category=limit_per_category)[0]
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        top = results[0]["name"] if results else ""
        lines.append(f"| {query} | {elapsed_ms:.1f} | {len(results)} | {top} |")

    return "\n".join(lines)
