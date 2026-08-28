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

CREATE TABLE IF NOT EXISTS market_snapshot (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    appid         INTEGER NOT NULL,
    taken_at      TEXT NOT NULL,
    scope         TEXT NOT NULL,
    account_count INTEGER NOT NULL,
    game_name     TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_appid_time
    ON market_snapshot(appid, scope, taken_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_unique
    ON market_snapshot(appid, taken_at, scope);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# คอลัมน์ที่เพิ่มทีหลัง — SQLite ไม่มี "ADD COLUMN IF NOT EXISTS" เลยต้องเช็คเอง
LATER_COLUMNS = {
    "snapshot": {
        "in_coop_topsellers": "INTEGER DEFAULT 0",
        "in_coop_upcoming": "INTEGER DEFAULT 0",
        "in_coop_new": "INTEGER DEFAULT 0",
        # ลำดับในผลค้นหาของ Steam — เป็นสัญญาณเดียวที่แยกเกมยังไม่วางขายออกจากกันได้
        # เพราะเกมพวกนั้นไม่มี CCU ไม่มีอันดับ ไม่มีอะไรให้วัดเลย
        "coop_topsellers_rank": "INTEGER",
        "coop_upcoming_rank": "INTEGER",
        "coop_new_rank": "INTEGER",
    },
    "title": {
        "metadata_failed_at": "TEXT",
        # ข้อมูลรีวิว — เก็บแยกจาก metadata เพราะขยับช้ากว่ามาก แคชได้นานกว่า
        "review_total": "INTEGER",
        "review_positive": "INTEGER",
        "review_ratio": "REAL",
        "review_desc": "TEXT",
        "playtime_median_h": "REAL",
        "playtime_sample": "INTEGER",
        "reviews_fetched_at": "TEXT",
        "reviews_failed_at": "TEXT",
    },
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in LATER_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
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
             ccu_rank, in_specials, in_new_releases, in_top_sellers, in_coming_soon,
             in_coop_topsellers, in_coop_upcoming, in_coop_new,
             coop_topsellers_rank, coop_upcoming_rank, coop_new_rank)
        VALUES (:appid, :taken_at, :ccu, :peak_in_game, :played_rank, :last_week_rank,
                :ccu_rank, :in_specials, :in_new_releases, :in_top_sellers,
                :in_coming_soon, :in_coop_topsellers, :in_coop_upcoming, :in_coop_new,
                :coop_topsellers_rank, :coop_upcoming_rank, :coop_new_rank)
        """,
        {"taken_at": taken_at, **row},
    )


def stale_appids(
    conn: sqlite3.Connection, max_age_days: int = 3, retry_failed_after_days: int = 14
) -> list[int]:
    """เกมที่ยังไม่เคยดึง metadata หรือดึงไว้นานแล้ว (ราคาเปลี่ยนบ่อยเพราะลดราคา)

    เกมที่ appdetails ไม่เคยคืนข้อมูล (บันเดิล/ไม่ขายในไทย) จะถูกพักไว้
    แทนที่จะยิงซ้ำทุกรอบตลอดไป — เดิมเสียเวลารอบละหลายวินาทีไปกับ 4 appid ที่ไม่มีวันสำเร็จ
    """
    cur = conn.execute(
        """
        SELECT appid FROM title
        WHERE (
                metadata_fetched_at IS NULL
                OR julianday('now') - julianday(metadata_fetched_at) > ?
              )
          AND (
                metadata_failed_at IS NULL
                OR julianday('now') - julianday(metadata_failed_at) > ?
              )
        """,
        (max_age_days, retry_failed_after_days),
    )
    return [r["appid"] for r in cur.fetchall()]


def mark_metadata_failed(conn: sqlite3.Connection, appid: int) -> None:
    conn.execute(
        "UPDATE title SET metadata_failed_at = ? WHERE appid = ?", (utcnow(), appid)
    )


def latest_snapshot_per_title(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute(
        """
        SELECT t.*, s.taken_at, s.ccu, s.peak_in_game, s.played_rank,
               s.last_week_rank, s.ccu_rank, s.in_specials, s.in_new_releases,
               s.in_top_sellers, s.in_coming_soon, s.in_coop_topsellers,
               s.in_coop_upcoming, s.in_coop_new, s.coop_topsellers_rank,
               s.coop_upcoming_rank, s.coop_new_rank
        FROM title t
        JOIN snapshot s ON s.id = (
            SELECT id FROM snapshot WHERE appid = t.appid
            ORDER BY taken_at DESC LIMIT 1
        )
        """
    )
    return cur.fetchall()


def ccu_history(conn: sqlite3.Connection, appid: int, limit: int = 30) -> list[tuple[str, int]]:
    """ค่า CCU วันละหนึ่งจุด — เอาค่าล่าสุดของแต่ละวัน

    ต้องยุบเป็นรายวัน ไม่ใช่คืนทุกแถว เพราะรันสแกนสองครั้งห่างกันหนึ่งนาทีได้
    ถ้าไม่ยุบ ค่ากลางจะถูกถ่วงด้วยจุดที่ซ้ำกันเองในวันเดียว แล้วอัตราการโตจะเพี้ยน
    (เคยทำให้เกมที่มีคนเล่น 177 คนขึ้นเป็นอันดับหนึ่งมาแล้ว)
    """
    cur = conn.execute(
        """
        SELECT date(taken_at) AS day, ccu, MAX(taken_at) AS latest
        FROM snapshot
        WHERE appid = ? AND ccu IS NOT NULL
        GROUP BY date(taken_at)
        ORDER BY day DESC LIMIT ?
        """,
        (appid, limit),
    )
    return [(r["latest"], r["ccu"]) for r in reversed(cur.fetchall())]


def scan_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(DISTINCT taken_at) AS n FROM snapshot")
    return cur.fetchone()["n"]


# ---------- ฝั่งตลาดจริง (สต็อกของร้านเช่า) ----------

def insert_market(
    conn: sqlite3.Connection, taken_at: str, scope: str, games: list[dict[str, Any]]
) -> int:
    """บันทึกสต็อก ณ เวลาหนึ่ง — scope เป็น 'platform' (ทุกร้านรวมกัน) หรือ 'mine'"""
    n = 0
    for g in games:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_snapshot
                (appid, taken_at, scope, account_count, game_name)
            VALUES (?,?,?,?,?)
            """,
            (g["app_id"], taken_at, scope, g.get("account_count", 0), g.get("game_name")),
        )
        n += 1
    return n


def latest_market(conn: sqlite3.Connection, scope: str = "platform") -> dict[int, int]:
    """สต็อกล่าสุดของแต่ละเกม -> {appid: จำนวนไอดี}"""
    cur = conn.execute(
        """
        SELECT appid, account_count FROM market_snapshot
        WHERE scope = ? AND taken_at = (
            SELECT MAX(taken_at) FROM market_snapshot WHERE scope = ?
        )
        """,
        (scope, scope),
    )
    return {r["appid"]: r["account_count"] for r in cur.fetchall()}


def market_delta(conn: sqlite3.Connection, scope: str = "platform") -> dict[int, int]:
    """สต็อกเปลี่ยนไปเท่าไรจากครั้งก่อนหน้า -> {appid: ส่วนต่าง}

    บวก = คู่แข่งกำลังลงทุนเพิ่มในเกมนั้น ซึ่งเป็นสัญญาณว่าเขาเห็นอะไรบางอย่าง
    """
    cur = conn.execute(
        "SELECT DISTINCT taken_at FROM market_snapshot WHERE scope = ? ORDER BY taken_at DESC LIMIT 2",
        (scope,),
    )
    times = [r["taken_at"] for r in cur.fetchall()]
    if len(times) < 2:
        return {}
    now, prev = times[0], times[1]
    cur = conn.execute(
        """
        SELECT a.appid, a.account_count - COALESCE(b.account_count, 0) AS d
        FROM market_snapshot a
        LEFT JOIN market_snapshot b
          ON b.appid = a.appid AND b.scope = a.scope AND b.taken_at = ?
        WHERE a.scope = ? AND a.taken_at = ?
        """,
        (prev, scope, now),
    )
    return {r["appid"]: r["d"] for r in cur.fetchall()}


def market_scan_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(DISTINCT taken_at) AS n FROM market_snapshot")
    return cur.fetchone()["n"]


def market_names(conn: sqlite3.Connection) -> dict[int, str]:
    """ชื่อเกมล่าสุดที่แพลตฟอร์มร้านเช่าใช้ — เอาไว้ตั้งชื่อ title stub"""
    cur = conn.execute(
        """
        SELECT appid, game_name FROM market_snapshot
        WHERE game_name IS NOT NULL
        GROUP BY appid HAVING MAX(taken_at)
        """
    )
    return {r["appid"]: r["game_name"] for r in cur.fetchall()}


def ccu_series(conn: sqlite3.Connection, appid: int, limit: int = 60) -> list[tuple[str, int]]:
    """CCU ทุกจุดที่เก็บได้ ไม่ยุบรายวัน — สำหรับวาดกราฟเส้น

    ต่างจาก ccu_history ที่ยุบเป็นวันละจุดเพื่อคำนวณอัตราโต ตรงนี้ต้องการ
    ความละเอียดตามที่เก็บจริง ยิ่งรัน scan ถี่ กราฟยิ่งละเอียด
    """
    cur = conn.execute(
        """
        SELECT taken_at, ccu FROM snapshot
        WHERE appid = ? AND ccu IS NOT NULL
        ORDER BY taken_at DESC LIMIT ?
        """,
        (appid, limit),
    )
    return [(r["taken_at"], r["ccu"]) for r in reversed(cur.fetchall())]


# ---------- นำข้อมูลเข้า/ออกเป็นข้อความ ----------
# เก็บฐานข้อมูลใน git เป็นไฟล์ .sql ไม่ใช่ไฟล์ .sqlite3
# เพราะไฟล์ไบนารีจะถูก git เก็บสำเนาเต็มทุก commit (ปีละหลายร้อย MB)
# ส่วนไฟล์ข้อความที่เพิ่มบรรทัดท้าย ๆ git ทำ delta ได้ดีมาก

def dump_sql(conn: sqlite3.Connection, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for line in conn.iterdump():
            f.write(line + "\n")
            n += 1
    return n


def restore_sql(path: Path, db_path: Path) -> bool:
    """สร้างฐานข้อมูลจากไฟล์ .sql — ใช้ตอนรันบนเครื่องที่ยังไม่มีฐานข้อมูล

    คืน False ถ้าไม่มีไฟล์ให้กู้ (ถือว่าเริ่มจากศูนย์ ไม่ใช่ความผิดพลาด)
    """
    if not path.exists():
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return True


# ---------- ข้อมูลรีวิว ----------

def appids_needing_reviews(
    conn: sqlite3.Connection, max_age_days: int = 7, limit: int = 60
) -> list[int]:
    """เกมที่ควรดึงรีวิว — ไม่ดึงทุกเกมในเรดาร์เพราะเปลืองเปล่า

    เอาเฉพาะเกมที่มีโอกาสได้ใช้จริง: เล่นหลายคนได้ ขาย (ไม่ฟรี) และเป็นเกมจริง
    บวกกับทุกเกมที่ตลาดเช่าสต็อกอยู่ ไม่ว่าจะเข้าเกณฑ์อื่นหรือไม่
    """
    cur = conn.execute(
        """
        SELECT t.appid FROM title t
        WHERE (
                t.reviews_fetched_at IS NULL
                OR julianday('now') - julianday(t.reviews_fetched_at) > :age
              )
          AND (
                t.reviews_failed_at IS NULL
                OR julianday('now') - julianday(t.reviews_failed_at) > 14
              )
          AND (
                (t.is_free = 0 AND (t.type IS NULL OR t.type = 'game')
                 AND (t.is_coop = 1 OR t.is_multi = 1))
                OR t.appid IN (SELECT appid FROM market_snapshot)
              )
        -- เรียงตามความสำคัญ ไม่ใช่ตาม appid
        -- เดิมเรียงด้วย t.appid ทำให้เกมเก่า appid ต่ำได้คิวก่อน
        -- แล้วเกมที่เป็นผู้สมัครจริง (ออกใหม่ appid สูง) ไม่เคยได้ข้อมูลรีวิวเลย
        ORDER BY
            t.reviews_fetched_at IS NOT NULL,          -- ที่ยังไม่เคยดึงมาก่อน
            t.appid IN (SELECT appid FROM market_snapshot) DESC,
            COALESCE((SELECT s.ccu FROM snapshot s WHERE s.appid = t.appid
                      ORDER BY s.taken_at DESC LIMIT 1), 0) DESC
        LIMIT :lim
        """,
        {"age": max_age_days, "lim": limit},
    )
    return [r["appid"] for r in cur.fetchall()]


def update_reviews(conn: sqlite3.Connection, appid: int, data: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE title SET
            review_total = :review_total,
            review_positive = :review_positive,
            review_ratio = :review_ratio,
            review_desc = :review_desc,
            playtime_median_h = :playtime_median_h,
            playtime_sample = :playtime_sample,
            reviews_fetched_at = :now
        WHERE appid = :appid
        """,
        {**data, "appid": appid, "now": utcnow()},
    )


def mark_reviews_failed(conn: sqlite3.Connection, appid: int) -> None:
    conn.execute(
        "UPDATE title SET reviews_failed_at = ? WHERE appid = ?", (utcnow(), appid)
    )
