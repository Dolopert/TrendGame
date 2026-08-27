"""ที่เก็บข้อมูล — SQLite ไฟล์เดียว

โครงสร้างสะท้อนคำศัพท์ในโดเมนตรง ๆ:
  title    = เกมหนึ่งเกม (คงอยู่ตลอด แก้ทับได้)
  snapshot = ค่าที่วัดได้ ณ เวลาหนึ่ง (เพิ่มอย่างเดียว ไม่แก้ย้อนหลัง)
Surge กับ Prospect ไม่ได้เก็บเป็นตาราง เพราะมันคือ "การตีความ" ของ snapshot
คำนวณสด ๆ ตอนอ่านได้ และเปลี่ยนสูตรทีหลังโดยไม่ต้องล้างข้อมูล
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS title (
    appid               INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    type                TEXT,
    is_free             INTEGER,
    header_image        TEXT,
    release_date        TEXT,
    coming_soon         INTEGER,
    genres              TEXT,
    category_ids        TEXT,
    is_single           INTEGER,
    is_multi            INTEGER,
    is_coop             INTEGER,
    is_online_pvp       INTEGER,
    has_family_sharing  INTEGER,
    price_final         INTEGER,
    price_currency      TEXT,
    discount_percent    INTEGER,
    metadata_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS snapshot (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    appid            INTEGER NOT NULL REFERENCES title(appid),
    taken_at         TEXT NOT NULL,
    ccu              INTEGER,
    peak_in_game     INTEGER,
    played_rank      INTEGER,
    last_week_rank   INTEGER,
    ccu_rank         INTEGER,
    in_specials      INTEGER DEFAULT 0,
    in_new_releases  INTEGER DEFAULT 0,
    in_top_sellers   INTEGER DEFAULT 0,
    in_coming_soon   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_snapshot_appid_time ON snapshot(appid, taken_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_unique ON snapshot(appid, taken_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_title(conn: sqlite3.Connection, appid: int, data: dict[str, Any]) -> None:
    """บันทึกข้อมูลเกมจาก appdetails — แปลง categories เป็นธงบูลีนไว้กรองเร็ว ๆ"""
    from .steam import (
        CAT_COOP,
        CAT_FAMILY_SHARING,
        CAT_MULTI,
        CAT_ONLINE_COOP,
        CAT_ONLINE_PVP,
        CAT_SINGLE,
    )

    cat_ids = [c["id"] for c in data.get("categories", []) if "id" in c]
    genres = [g["description"] for g in data.get("genres", [])]
    price = data.get("price_overview") or {}
    release = data.get("release_date") or {}

    conn.execute(
        """
        INSERT INTO title (appid, name, type, is_free, header_image, release_date,
                           coming_soon, genres, category_ids, is_single, is_multi,
                           is_coop, is_online_pvp, has_family_sharing, price_final,
                           price_currency, discount_percent, metadata_fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(appid) DO UPDATE SET
            name=excluded.name, type=excluded.type, is_free=excluded.is_free,
            header_image=excluded.header_image, release_date=excluded.release_date,
            coming_soon=excluded.coming_soon, genres=excluded.genres,
            category_ids=excluded.category_ids, is_single=excluded.is_single,
            is_multi=excluded.is_multi, is_coop=excluded.is_coop,
            is_online_pvp=excluded.is_online_pvp,
            has_family_sharing=excluded.has_family_sharing,
            price_final=excluded.price_final, price_currency=excluded.price_currency,
            discount_percent=excluded.discount_percent,
            metadata_fetched_at=excluded.metadata_fetched_at
        """,
        (
            appid,
            data.get("name") or f"app {appid}",
            data.get("type"),
            1 if data.get("is_free") else 0,
            data.get("header_image"),
            release.get("date"),
            1 if release.get("coming_soon") else 0,
            json.dumps(genres, ensure_ascii=False),
            json.dumps(cat_ids),
            int(CAT_SINGLE in cat_ids),
            int(CAT_MULTI in cat_ids),
            int(CAT_COOP in cat_ids or CAT_ONLINE_COOP in cat_ids),
            int(CAT_ONLINE_PVP in cat_ids),
            int(CAT_FAMILY_SHARING in cat_ids),
            price.get("final"),
            price.get("currency"),
            price.get("discount_percent"),
            utcnow(),
        ),
    )


def ensure_stub_title(conn: sqlite3.Connection, appid: int, name: str) -> None:
    """สร้างแถว title เปล่าไว้ก่อน เผื่อ appdetails ยังไม่ได้ดึง (กัน FK พัง)"""
    conn.execute(
        "INSERT OR IGNORE INTO title (appid, name) VALUES (?, ?)", (appid, name)
    )


def insert_snapshot(conn: sqlite3.Connection, taken_at: str, row: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO snapshot
            (appid, taken_at, ccu, peak_in_game, played_rank, last_week_rank,
             ccu_rank, in_specials, in_new_releases, in_top_sellers, in_coming_soon)
        VALUES (:appid, :taken_at, :ccu, :peak_in_game, :played_rank, :last_week_rank,
                :ccu_rank, :in_specials, :in_new_releases, :in_top_sellers,
                :in_coming_soon)
        """,
        {"taken_at": taken_at, **row},
    )


def stale_appids(conn: sqlite3.Connection, max_age_days: int = 3) -> list[int]:
    """เกมที่ยังไม่เคยดึง metadata หรือดึงไว้นานแล้ว (ราคาเปลี่ยนบ่อยเพราะลดราคา)"""
    cur = conn.execute(
        """
        SELECT appid FROM title
        WHERE metadata_fetched_at IS NULL
           OR julianday('now') - julianday(metadata_fetched_at) > ?
        """,
        (max_age_days,),
    )
    return [r["appid"] for r in cur.fetchall()]


def latest_snapshot_per_title(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT t.*, s.taken_at, s.ccu, s.peak_in_game, s.played_rank,
               s.last_week_rank, s.ccu_rank, s.in_specials, s.in_new_releases,
               s.in_top_sellers, s.in_coming_soon
        FROM title t
        JOIN snapshot s ON s.id = (
            SELECT id FROM snapshot WHERE appid = t.appid
            ORDER BY taken_at DESC LIMIT 1
        )
        """
    )
    return cur.fetchall()


def ccu_history(conn: sqlite3.Connection, appid: int, limit: int = 30) -> list[tuple[str, int]]:
    cur = conn.execute(
        """
        SELECT taken_at, ccu FROM snapshot
        WHERE appid = ? AND ccu IS NOT NULL
        ORDER BY taken_at DESC LIMIT ?
        """,
        (appid, limit),
    )
    return [(r["taken_at"], r["ccu"]) for r in reversed(cur.fetchall())]


def scan_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(DISTINCT taken_at) AS n FROM snapshot")
    return cur.fetchone()["n"]
