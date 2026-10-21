"""SQLite-backed app registry (ROADMAP.md 2.3, 2.8)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@dataclass
class AppRecord:
    app_id: str
    name: str
    description: str
    capability_tags: list[str]
    input_schema: dict
    output_schema: dict
    exec_manifest: dict
    creation_source: str  # generated | opensource_installed | hybrid
    version: str
    created_at: str
    updated_at: str
    source_ref: str | None = None
    usage_count: int = 0
    last_used_at: str | None = None
    success_rate: float = 0.0

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> "AppRecord":
        return cls(
            app_id=row["app_id"],
            name=row["name"],
            description=row["description"],
            capability_tags=json.loads(row["capability_tags"]),
            input_schema=json.loads(row["input_schema"]),
            output_schema=json.loads(row["output_schema"]),
            exec_manifest=json.loads(row["exec_manifest"]),
            creation_source=row["creation_source"],
            source_ref=row["source_ref"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            usage_count=row["usage_count"],
            last_used_at=row["last_used_at"],
            success_rate=row["success_rate"],
        )


class AppRegistry:
    """Thin wrapper around the `apps`/`app_tags` tables.

    One connection per instance; SQLite handles the single-file-no-server
    story ROADMAP.md 2.3 wants for an immutable-OS-friendly registry.
    """

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA_PATH.read_text())

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AppRegistry":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def register(self, app: AppRecord) -> None:
        """Insert or replace an app (ROADMAP.md 2.8: registration pipeline)."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO apps (
                    app_id, name, description, capability_tags,
                    input_schema, output_schema, exec_manifest,
                    creation_source, source_ref, version,
                    created_at, updated_at, usage_count, last_used_at, success_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    capability_tags=excluded.capability_tags,
                    input_schema=excluded.input_schema,
                    output_schema=excluded.output_schema,
                    exec_manifest=excluded.exec_manifest,
                    creation_source=excluded.creation_source,
                    source_ref=excluded.source_ref,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (
                    app.app_id,
                    app.name,
                    app.description,
                    json.dumps(app.capability_tags),
                    json.dumps(app.input_schema),
                    json.dumps(app.output_schema),
                    json.dumps(app.exec_manifest),
                    app.creation_source,
                    app.source_ref,
                    app.version,
                    app.created_at,
                    app.updated_at,
                    app.usage_count,
                    app.last_used_at,
                    app.success_rate,
                ),
            )
            self._conn.execute("DELETE FROM app_tags WHERE app_id = ?", (app.app_id,))
            self._conn.executemany(
                "INSERT INTO app_tags (app_id, tag) VALUES (?, ?)",
                [(app.app_id, tag) for tag in app.capability_tags],
            )

    def list_all(self) -> list[AppRecord]:
        """All registered apps, alphabetical -- powers the Phase 4 shell's
        installed-program icon dock (ROADMAP.md 2.1 하단 아이콘)."""
        rows = self._conn.execute("SELECT * FROM apps ORDER BY name").fetchall()
        return [AppRecord._from_row(row) for row in rows]

    def find_by_tags(self, tags: list[str]) -> list[AppRecord]:
        """Tier-1 filter (ROADMAP.md 2.3 step 1): apps sharing at least one
        capability tag with the request, ranked by tag-overlap count then
        success_rate to break ties (2.3: '동점 후보 발생 시 success_rate
        기준 우선순위 결정')."""
        if not tags:
            return []
        placeholders = ",".join("?" for _ in tags)
        rows = self._conn.execute(
            f"""
            SELECT a.*, COUNT(t.tag) AS overlap
            FROM apps a
            JOIN app_tags t ON t.app_id = a.app_id
            WHERE t.tag IN ({placeholders})
            GROUP BY a.app_id
            ORDER BY overlap DESC, a.success_rate DESC
            """,
            tags,
        ).fetchall()
        return [AppRecord._from_row(row) for row in rows]

    def record_usage(self, app_id: str, used_at: str, success: bool) -> None:
        row = self._conn.execute(
            "SELECT usage_count, success_rate FROM apps WHERE app_id = ?", (app_id,)
        ).fetchone()
        if row is None:
            return
        usage_count = row["usage_count"] + 1
        prior_successes = row["success_rate"] * row["usage_count"]
        success_rate = (prior_successes + (1 if success else 0)) / usage_count
        with self._conn:
            self._conn.execute(
                "UPDATE apps SET usage_count = ?, last_used_at = ?, success_rate = ? WHERE app_id = ?",
                (usage_count, used_at, success_rate, app_id),
            )
