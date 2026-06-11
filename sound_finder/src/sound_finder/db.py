from __future__ import annotations

import contextlib
import json
import re
import sqlite3
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "sound_finder.sqlite"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class PlanCategory:
    name: str
    direction: str
    keywords: list[str]
    include: bool = True
    recipe: list[dict[str, Any]] = field(default_factory=list)
    recipe_style: str = "realistic_tactile"


class SoundFinderDB:
    def __init__(self, path: Path = DB_PATH) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audio_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                extension TEXT NOT NULL,
                folder TEXT NOT NULL,
                duration REAL,
                size INTEGER NOT NULL,
                modified REAL NOT NULL,
                indexed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                requirement TEXT NOT NULL,
                reaper_project_name TEXT NOT NULL DEFAULT '',
                reaper_project_path TEXT NOT NULL DEFAULT '',
                reaper_project_updated_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                recipe_json TEXT NOT NULL DEFAULT '[]',
                recipe_style TEXT NOT NULL DEFAULT 'realistic_tactile',
                include_search INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS search_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                audio_file_id INTEGER NOT NULL,
                score REAL NOT NULL,
                matched_terms TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, category_id, audio_file_id),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
                FOREIGN KEY (audio_file_id) REFERENCES audio_files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                layer_name TEXT NOT NULL,
                layer_role TEXT NOT NULL,
                audio_file_id INTEGER NOT NULL,
                score REAL NOT NULL,
                reason TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, category_id, layer_name),
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
                FOREIGN KEY (audio_file_id) REFERENCES audio_files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS combo_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                recipe_style TEXT NOT NULL,
                recipe_json TEXT NOT NULL,
                recommendations_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_audio_files_name ON audio_files(name);
            CREATE INDEX IF NOT EXISTS idx_audio_files_folder ON audio_files(folder);
            CREATE INDEX IF NOT EXISTS idx_results_session ON search_results(session_id);
            CREATE INDEX IF NOT EXISTS idx_results_category ON search_results(category_id);
            CREATE INDEX IF NOT EXISTS idx_combo_history_category ON combo_history(category_id);
            """
        )
        self._ensure_column("categories", "recipe_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column(
            "categories",
            "recipe_style",
            "TEXT NOT NULL DEFAULT 'realistic_tactile'",
        )
        self._ensure_column("sessions", "reaper_project_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "reaper_project_path", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "reaper_project_updated_at", "TEXT NOT NULL DEFAULT ''")
        self.conn.commit()
        self._ensure_audio_files_fts()

    def _fts5_available(self) -> bool:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts5_probe USING fts5(x)")
            self.conn.execute("DROP TABLE IF EXISTS temp._fts5_probe")
        except sqlite3.Error:
            return False
        return True

    def _ensure_audio_files_fts(self) -> None:
        if not self._fts5_available():
            return
        self.conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS audio_files_fts USING fts5(
                path,
                name,
                folder,
                content='audio_files',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            );

            CREATE TRIGGER IF NOT EXISTS audio_files_ai AFTER INSERT ON audio_files BEGIN
                INSERT INTO audio_files_fts(rowid, path, name, folder)
                VALUES (new.id, new.path, new.name, new.folder);
            END;

            CREATE TRIGGER IF NOT EXISTS audio_files_ad AFTER DELETE ON audio_files BEGIN
                INSERT INTO audio_files_fts(audio_files_fts, rowid, path, name, folder)
                VALUES('delete', old.id, old.path, old.name, old.folder);
            END;

            CREATE TRIGGER IF NOT EXISTS audio_files_au AFTER UPDATE ON audio_files BEGIN
                INSERT INTO audio_files_fts(audio_files_fts, rowid, path, name, folder)
                VALUES('delete', old.id, old.path, old.name, old.folder);
                INSERT INTO audio_files_fts(rowid, path, name, folder)
                VALUES (new.id, new.path, new.name, new.folder);
            END;
            """
        )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] == column for row in rows):
            return
        try:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def audio_fts_ready(self) -> bool:
        return self.get_setting("audio_files_fts_ready", "0") == "1"

    def audio_fts_status(self) -> dict[str, Any]:
        exists = self.conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'audio_files_fts'
            """
        ).fetchone() is not None
        indexed_rows = None
        if exists:
            try:
                docsize_exists = self.conn.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'audio_files_fts_docsize'
                    """
                ).fetchone() is not None
                if docsize_exists:
                    indexed_rows = self.conn.execute(
                        "SELECT COUNT(*) AS total FROM audio_files_fts_docsize"
                    ).fetchone()["total"]
            except sqlite3.Error:
                indexed_rows = None
        return {
            "available": self._fts5_available(),
            "exists": exists,
            "ready": self.audio_fts_ready(),
            "rebuilt_at": self.get_setting("audio_files_fts_rebuilt_at", ""),
            "audio_count_at_rebuild": self.get_setting("audio_files_fts_audio_count", ""),
            "indexed_rows_probe": indexed_rows,
        }

    def rebuild_audio_files_fts(self) -> dict[str, Any]:
        if not self._fts5_available():
            raise RuntimeError("SQLite FTS5 is not available")
        self._ensure_audio_files_fts()
        self.conn.execute("INSERT INTO audio_files_fts(audio_files_fts) VALUES('rebuild')")
        audio_count = self.conn.execute("SELECT COUNT(*) AS total FROM audio_files").fetchone()["total"]
        stamp = now_text()
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("audio_files_fts_ready", "1"),
        )
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("audio_files_fts_rebuilt_at", stamp),
        )
        self.conn.execute(
            """
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("audio_files_fts_audio_count", str(audio_count)),
        )
        self.conn.commit()
        return {
            "rebuilt_at": stamp,
            "audio_count": int(audio_count),
        }

    def upsert_audio_file(
        self,
        *,
        path: Path,
        duration: float | None,
        size: int,
        modified: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO audio_files(path, name, extension, folder, duration, size, modified, indexed_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                extension = excluded.extension,
                folder = excluded.folder,
                duration = excluded.duration,
                size = excluded.size,
                modified = excluded.modified,
                indexed_at = excluded.indexed_at
            """,
            (
                str(path),
                path.name,
                path.suffix.lower().lstrip("."),
                str(path.parent),
                duration,
                size,
                modified,
                now_text(),
            ),
        )

    def commit(self) -> None:
        self.conn.commit()

    def _path_filter_sql(
        self,
        column: str,
        library_root: str | Path | None,
    ) -> tuple[str, list[Any]]:
        if not library_root:
            return "", []
        root_text = str(library_root).strip().rstrip("\\/")
        if not root_text:
            return "", []

        variants = {
            root_text,
            root_text.replace("\\", "/"),
            root_text.replace("/", "\\"),
            str(Path(root_text)),
        }
        clauses: list[str] = []
        params: list[Any] = []
        for prefix in sorted(variants):
            clean = prefix.rstrip("\\/")
            if not clean:
                continue
            clauses.append(f"{column} = ?")
            params.append(clean)
            clauses.append(f"{column} LIKE ?")
            params.append(clean + "\\%")
            clauses.append(f"{column} LIKE ?")
            params.append(clean + "/%")

        if not clauses:
            return "", []
        return f"AND ({' OR '.join(clauses)})", params

    def _usable_audio_sql(self, path_column: str = "path", name_column: str = "name") -> str:
        return (
            f"AND {name_column} NOT LIKE '._%' "
            f"AND {path_column} NOT LIKE '%\\__MACOSX\\%' "
            f"AND {path_column} NOT LIKE '%/__MACOSX/%'"
        )

    def count_audio_files(self, library_root: str | Path | None = None) -> int:
        where, params = self._path_filter_sql("path", library_root)
        row = self.conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM audio_files
            WHERE 1 = 1 {where}
            {self._usable_audio_sql()}
            """,
            params,
        ).fetchone()
        return int(row["total"])

    def list_audio_files(self, library_root: str | Path | None = None) -> list[dict[str, Any]]:
        where, params = self._path_filter_sql("path", library_root)
        rows = self.conn.execute(
            f"""
            SELECT id, path, name, extension, folder, duration, size, modified
            FROM audio_files
            WHERE 1 = 1 {where}
            {self._usable_audio_sql()}
            ORDER BY name COLLATE NOCASE
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def audio_file_fingerprints(
        self,
        library_root: str | Path | None = None,
    ) -> dict[str, tuple[int, float]]:
        where, params = self._path_filter_sql("path", library_root)
        rows = self.conn.execute(
            f"""
            SELECT path, size, modified
            FROM audio_files
            WHERE 1 = 1 {where}
            {self._usable_audio_sql()}
            """,
            params,
        ).fetchall()
        return {
            str(row["path"]): (int(row["size"]), float(row["modified"]))
            for row in rows
        }

    def candidate_audio_files(
        self,
        keywords: list[str],
        library_root: str | Path | None = None,
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        tokens = self._search_tokens(keywords)
        if tokens and self.audio_fts_ready():
            with contextlib.suppress(sqlite3.Error):
                return self._candidate_audio_files_fts(tokens, library_root, limit)

        library_clause, library_params = self._path_filter_sql("path", library_root)
        params: list[Any] = list(library_params)
        token_clause = ""
        if tokens:
            token_clause = "AND (" + " OR ".join("LOWER(path) LIKE ?" for _ in tokens[:18]) + ")"
            params.extend(f"%{token}%" for token in tokens[:18])
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT id, path, name, extension, folder, duration, size, modified
            FROM audio_files
            WHERE 1 = 1
            {library_clause}
            {token_clause}
            {self._usable_audio_sql()}
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def _search_tokens(self, keywords: list[str]) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        generic = {
            "sound",
            "audio",
            "short",
            "soft",
            "small",
            "user",
            "interface",
            "realistic",
            "positive",
        }
        for keyword in keywords:
            for token in re.split(r"[^a-z0-9]+", keyword.lower()):
                if len(token) < 4 or token in generic or token in seen:
                    continue
                seen.add(token)
                tokens.append(token)
        return tokens

    def _candidate_audio_files_fts(
        self,
        tokens: list[str],
        library_root: str | Path | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        fts_query = " OR ".join(f"{token}*" for token in tokens[:18])
        library_clause, library_params = self._path_filter_sql("a.path", library_root)
        params: list[Any] = [fts_query]
        params.extend(library_params)
        params.append(limit)

        rows = self.conn.execute(
            f"""
            SELECT a.id, a.path, a.name, a.extension, a.folder, a.duration, a.size, a.modified
            FROM audio_files_fts
            JOIN audio_files AS a ON a.id = audio_files_fts.rowid
            WHERE audio_files_fts MATCH ?
            {library_clause}
            {self._usable_audio_sql("a.path", "a.name")}
            ORDER BY bm25(audio_files_fts, 0.8, 2.0, 0.8)
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_audio_files_outside_library(self, library_root: str | Path | None) -> int:
        where, params = self._path_filter_sql("path", library_root)
        if not where:
            return 0
        inside_clause = where.removeprefix("AND ")
        cursor = self.conn.execute(
            f"DELETE FROM audio_files WHERE NOT {inside_clause}",
            params,
        )
        self.conn.commit()
        return int(cursor.rowcount)

    def delete_audio_files_in_library(self, library_root: str | Path | None) -> int:
        where, params = self._path_filter_sql("path", library_root)
        if not where:
            return 0
        cursor = self.conn.execute(
            f"DELETE FROM audio_files WHERE 1 = 1 {where}",
            params,
        )
        self.conn.commit()
        return int(cursor.rowcount)

    def delete_unusable_audio_files(self) -> int:
        cursor = self.conn.execute(
            """
            DELETE FROM audio_files
            WHERE name LIKE '._%'
               OR path LIKE '%\\__MACOSX\\%'
               OR path LIKE '%/__MACOSX/%'
            """
        )
        self.conn.commit()
        return int(cursor.rowcount)

    def create_session(self, title: str, requirement: str) -> int:
        stamp = now_text()
        cursor = self.conn.execute(
            """
            INSERT INTO sessions(title, requirement, created_at, updated_at)
            VALUES(?, ?, ?, ?)
            """,
            (title, requirement, stamp, stamp),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def replace_plan(self, session_id: int, requirement: str, plan: list[PlanCategory]) -> dict[int, int]:
        self.conn.execute(
            "UPDATE sessions SET requirement = ?, updated_at = ? WHERE id = ?",
            (requirement, now_text(), session_id),
        )
        self.conn.execute("DELETE FROM categories WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM search_results WHERE session_id = ?", (session_id,))

        category_ids: dict[int, int] = {}
        for index, category in enumerate(plan):
            cursor = self.conn.execute(
                """
                INSERT INTO categories(
                    session_id,
                    name,
                    direction,
                    keywords_json,
                    recipe_json,
                    recipe_style,
                    include_search,
                    sort_order
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    category.name,
                    category.direction,
                    json.dumps(category.keywords, ensure_ascii=False),
                    json.dumps(category.recipe, ensure_ascii=False),
                    category.recipe_style,
                    1 if category.include else 0,
                    index,
                ),
            )
            category_ids[index] = int(cursor.lastrowid)

        self.conn.commit()
        return category_ids

    def update_session_reaper_project(
        self,
        session_id: int,
        *,
        project_name: str,
        project_path: str | Path,
    ) -> None:
        stamp = now_text()
        self.conn.execute(
            """
            UPDATE sessions
            SET reaper_project_name = ?,
                reaper_project_path = ?,
                reaper_project_updated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (project_name, str(project_path), stamp, stamp, session_id),
        )
        self.conn.commit()

    def save_results(
        self,
        session_id: int,
        category_id: int,
        results: list[dict[str, Any]],
    ) -> None:
        for result in results:
            audio_file_id = result.get("id") or result.get("audio_file_id")
            if not audio_file_id:
                continue
            matched_terms = result.get("matched_terms", "")
            if isinstance(matched_terms, list):
                matched_terms = ", ".join(str(item) for item in matched_terms)
            self.conn.execute(
                """
                INSERT INTO search_results(
                    session_id, category_id, audio_file_id, score, matched_terms, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, category_id, audio_file_id) DO UPDATE SET
                    score = excluded.score,
                    matched_terms = excluded.matched_terms
                """,
                (
                    session_id,
                    category_id,
                    audio_file_id,
                    result["score"],
                    str(matched_terms),
                    now_text(),
                ),
            )
        self.conn.commit()

    def replace_category_results(
        self,
        session_id: int,
        category_id: int,
        results: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            "DELETE FROM search_results WHERE session_id = ? AND category_id = ?",
            (session_id, category_id),
        )
        self.conn.commit()
        self.save_results(session_id, category_id, results)

    def merge_category_results(
        self,
        session_id: int,
        category_id: int,
        results: list[dict[str, Any]],
    ) -> None:
        self.save_results(session_id, category_id, results)

    def replace_category_results_from_history(
        self,
        session_id: int,
        category_id: int,
        results: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            "DELETE FROM search_results WHERE session_id = ? AND category_id = ?",
            (session_id, category_id),
        )
        stamp = now_text()
        for result in results:
            audio_file_id = result.get("audio_file_id") or result.get("id")
            if not audio_file_id:
                continue
            matched_terms = result.get("matched_terms", "")
            if isinstance(matched_terms, list):
                matched_terms = ", ".join(str(item) for item in matched_terms)
            self.conn.execute(
                """
                INSERT INTO search_results(
                    session_id,
                    category_id,
                    audio_file_id,
                    score,
                    matched_terms,
                    favorite,
                    used,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    category_id,
                    int(audio_file_id),
                    float(result.get("score", 0.0)),
                    str(matched_terms),
                    1 if result.get("favorite") else 0,
                    1 if result.get("used") else 0,
                    stamp,
                ),
            )
        self.conn.commit()

    def list_sessions(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                title,
                requirement,
                reaper_project_name,
                reaper_project_path,
                reaper_project_updated_at,
                created_at,
                updated_at
            FROM sessions
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                title,
                requirement,
                reaper_project_name,
                reaper_project_path,
                reaper_project_updated_at,
                created_at,
                updated_at
            FROM sessions WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_categories(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                session_id,
                name,
                direction,
                keywords_json,
                recipe_json,
                recipe_style,
                include_search,
                sort_order
            FROM categories
            WHERE session_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        categories: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["keywords"] = json.loads(item.pop("keywords_json"))
            item["recipe"] = json.loads(item.pop("recipe_json") or "[]")
            item["include"] = bool(item.pop("include_search"))
            categories.append(item)
        return categories

    def update_category_recipe(
        self,
        category_id: int,
        *,
        recipe: list[dict[str, Any]],
        recipe_style: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE categories
            SET recipe_json = ?, recipe_style = ?
            WHERE id = ?
            """,
            (json.dumps(recipe, ensure_ascii=False), recipe_style, category_id),
        )
        self.conn.commit()

    def list_results(
        self,
        session_id: int,
        category_id: int | None = None,
        library_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [session_id]
        category_clause = ""
        if category_id is not None:
            category_clause = "AND r.category_id = ?"
            params.append(category_id)
        library_clause, library_params = self._path_filter_sql("a.path", library_root)
        params.extend(library_params)

        rows = self.conn.execute(
            f"""
            SELECT
                r.id AS result_id,
                r.session_id,
                r.category_id,
                r.score,
                r.matched_terms,
                r.favorite,
                r.used,
                c.name AS category_name,
                c.direction AS category_direction,
                a.id AS audio_file_id,
                a.path,
                a.name,
                a.extension,
                a.folder,
                a.duration,
                a.size
            FROM search_results r
            JOIN audio_files a ON a.id = r.audio_file_id
            JOIN categories c ON c.id = r.category_id
            WHERE r.session_id = ?
            {category_clause}
            {library_clause}
            {self._usable_audio_sql('a.path', 'a.name')}
            ORDER BY r.score DESC, a.name COLLATE NOCASE ASC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def result_counts_by_category(
        self,
        session_id: int,
        library_root: str | Path | None = None,
    ) -> dict[int, int]:
        library_clause, params = self._path_filter_sql("a.path", library_root)
        rows = self.conn.execute(
            f"""
            SELECT r.category_id, COUNT(*) AS total
            FROM search_results r
            JOIN audio_files a ON a.id = r.audio_file_id
            WHERE r.session_id = ?
            {library_clause}
            {self._usable_audio_sql('a.path', 'a.name')}
            GROUP BY category_id
            """,
            [session_id] + params,
        ).fetchall()
        return {int(row["category_id"]): int(row["total"]) for row in rows}

    def update_result_flags(
        self,
        result_id: int,
        *,
        favorite: bool | None = None,
        used: bool | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[Any] = []
        if favorite is not None:
            updates.append("favorite = ?")
            params.append(1 if favorite else 0)
        if used is not None:
            updates.append("used = ?")
            params.append(1 if used else 0)
        if not updates:
            return
        params.append(result_id)
        self.conn.execute(f"UPDATE search_results SET {', '.join(updates)} WHERE id = ?", params)
        self.conn.commit()

    def clear_recommendations(self, session_id: int, category_id: int) -> None:
        self.conn.execute(
            "DELETE FROM recommendations WHERE session_id = ? AND category_id = ?",
            (session_id, category_id),
        )
        self.conn.commit()

    def save_recommendations(
        self,
        session_id: int,
        category_id: int,
        recommendations: list[dict[str, Any]],
        source: str,
    ) -> None:
        stamp = now_text()
        self.conn.execute(
            "DELETE FROM recommendations WHERE session_id = ? AND category_id = ?",
            (session_id, category_id),
        )
        for item in recommendations:
            self.conn.execute(
                """
                INSERT INTO recommendations(
                    session_id,
                    category_id,
                    layer_name,
                    layer_role,
                    audio_file_id,
                    score,
                    reason,
                    source,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    category_id,
                    item["layer_name"],
                    item["layer_role"],
                    item["audio_file_id"],
                    item["score"],
                    item["reason"],
                    source,
                    stamp,
                ),
            )
        self.conn.commit()

    def list_recommendations(
        self,
        session_id: int,
        category_id: int,
        library_root: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        library_clause, library_params = self._path_filter_sql("a.path", library_root)
        rows = self.conn.execute(
            f"""
            SELECT
                rec.id AS recommendation_id,
                rec.session_id,
                rec.category_id,
                rec.layer_name,
                rec.layer_role,
                rec.score,
                rec.reason,
                rec.source,
                rec.created_at,
                a.id AS audio_file_id,
                a.path,
                a.name,
                a.extension,
                a.folder,
                a.duration,
                a.size
            FROM recommendations rec
            JOIN audio_files a ON a.id = rec.audio_file_id
            WHERE rec.session_id = ? AND rec.category_id = ?
            {library_clause}
            {self._usable_audio_sql('a.path', 'a.name')}
            ORDER BY rec.id ASC
            """,
            [session_id, category_id] + library_params,
        ).fetchall()
        return [dict(row) for row in rows]

    def save_combo_history(
        self,
        session_id: int,
        category_id: int,
        *,
        title: str,
        source: str,
        recipe_style: str,
        recipe: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        results: list[dict[str, Any]],
    ) -> None:
        rec_snapshot = [
            {
                "layer_name": item.get("layer_name", ""),
                "layer_role": item.get("layer_role", ""),
                "audio_file_id": item.get("audio_file_id"),
                "score": item.get("score", 0.0),
                "reason": item.get("reason", ""),
            }
            for item in recommendations
            if item.get("audio_file_id")
        ]
        result_snapshot = [
            {
                "audio_file_id": item.get("audio_file_id") or item.get("id"),
                "score": item.get("score", 0.0),
                "matched_terms": item.get("matched_terms", ""),
                "favorite": bool(item.get("favorite", False)),
                "used": bool(item.get("used", False)),
            }
            for item in results
            if item.get("audio_file_id") or item.get("id")
        ]
        self.conn.execute(
            """
            INSERT INTO combo_history(
                session_id,
                category_id,
                title,
                source,
                recipe_style,
                recipe_json,
                recommendations_json,
                results_json,
                created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                category_id,
                title,
                source,
                recipe_style,
                json.dumps(recipe, ensure_ascii=False),
                json.dumps(rec_snapshot, ensure_ascii=False),
                json.dumps(result_snapshot, ensure_ascii=False),
                now_text(),
            ),
        )
        self.conn.commit()

    def list_combo_history(
        self,
        session_id: int,
        category_id: int,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                id,
                session_id,
                category_id,
                title,
                source,
                recipe_style,
                recipe_json,
                recommendations_json,
                results_json,
                created_at
            FROM combo_history
            WHERE session_id = ? AND category_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, category_id, limit),
        ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["recipe"] = json.loads(item.pop("recipe_json") or "[]")
            item["recommendations"] = json.loads(item.pop("recommendations_json") or "[]")
            item["results"] = json.loads(item.pop("results_json") or "[]")
            history.append(item)
        return history

    def get_combo_history(self, history_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT
                id,
                session_id,
                category_id,
                title,
                source,
                recipe_style,
                recipe_json,
                recommendations_json,
                results_json,
                created_at
            FROM combo_history
            WHERE id = ?
            """,
            (history_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["recipe"] = json.loads(item.pop("recipe_json") or "[]")
        item["recommendations"] = json.loads(item.pop("recommendations_json") or "[]")
        item["results"] = json.loads(item.pop("results_json") or "[]")
        return item
