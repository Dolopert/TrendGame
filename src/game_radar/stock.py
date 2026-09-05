"""สต็อกไอดีของร้าน — ไอดี · เกมในไอดี · การเช่า

**ฐานข้อมูลคนละไฟล์กับ radar.sqlite3 โดยเจตนา** เพราะ `radar.sql` ถูก dump ขึ้น
repo สาธารณะทุกคืน ถ้าเอาอีเมลกับชื่อลูกค้าไปใส่รวมกัน มันจะขึ้น GitHub ให้คน
ทั้งโลกอ่านโดยไม่มีใครทันสังเกต ไฟล์นี้จึงอยู่ที่ `data/stock.sqlite3` ซึ่ง
.gitignore ดักไว้ และ **ไม่มีคำสั่ง dump** ให้เผลอใช้ สำรองด้วย `stock export`
ไปนอกโปรเจกต์เอง

**ห้ามเก็บรหัสผ่านและ revocation code ในนี้เด็ดขาด** — เก็บได้แค่ `vault_ref`
คือ *ชื่อรายการ* ในโปรแกรมจัดการรหัสผ่าน (Bitwarden ฯลฯ) ไฟล์ SQLite ไม่ได้เข้ารหัส
ใครหยิบไฟล์ไปก็อ่านได้หมด และ revocation code คือกุญแจถอน Steam Guard
ซึ่งมีค่าเท่ากับตัวบัญชีเอง

คำศัพท์ (ต่อจาก CONTEXT.md):
  Account = ไอดี Steam หนึ่งไอดีที่ร้านถือไว้ — เป็นหน่วยที่ปล่อยเช่า
  License = เกมหนึ่งเกมที่ซื้อไว้ในไอดีหนึ่ง (หนึ่งไอดีมีหลายเกมได้)
  Rental  = การเช่าหนึ่งครั้ง ผูกกับ Account ไม่ใช่ License
            เพราะคนเช่าได้ทั้งไอดี เกมอื่นในไอดีนั้นจึงถูกล็อกไปด้วย
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL UNIQUE,   -- ชื่อเรียกในร้าน เช่น A01
    email       TEXT NOT NULL UNIQUE,   -- อีเมลที่ผูกกับ Steam
    login       TEXT,                   -- ชื่อบัญชี Steam (ไม่ใช่รหัสผ่าน)
    vault_ref   TEXT,                   -- ชื่อรายการใน password manager เท่านั้น
    status      TEXT NOT NULL DEFAULT 'active',  -- active | paused | retired
    guard_note  TEXT,                   -- authenticator อยู่เครื่องไหน
    created_on  TEXT NOT NULL,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS license (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES account(id),
    appid       INTEGER NOT NULL,
    game_name   TEXT,                   -- เก็บซ้ำไว้ให้ stock อ่านได้โดยไม่ต้องมี radar
    cost_baht   REAL,
    bought_on   TEXT NOT NULL,
    note        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_license_unique ON license(account_id, appid);

-- ผูกกับ account ไม่ใช่ license: คนเช่าได้ทั้งไอดี appid บอกแค่ว่าเช่าเพราะเกมไหน
-- ซึ่งเป็นข้อมูลดีมานด์ที่ทั้งระบบยังไม่มี (ดู UPDATE.md 3.3 — ที่เก็บอยู่คือซัพพลาย)
CREATE TABLE IF NOT EXISTS rental (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES account(id),
    appid       INTEGER,
    renter      TEXT,
    contact     TEXT,
    starts_on   TEXT NOT NULL,
    ends_on     TEXT NOT NULL,
    price_baht  REAL,
    returned_on TEXT,                   -- ว่าง = ยังไม่คืน
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_rental_account ON rental(account_id, starts_on);
CREATE INDEX IF NOT EXISTS idx_rental_appid ON rental(appid, starts_on);
"""


def today() -> str:
    """วันที่ตามเครื่อง ไม่ใช่ UTC — รอบเช่าเป็นเรื่องวันตามเวลาไทย
    ถ้าใช้ UTC ช่วง 00:00-07:00 ของไทยจะถูกนับเป็นเมื่อวาน
    """
    return date.today().isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _d(s: str) -> date:
    return date.fromisoformat(s)


# ---------- ไอดี ----------

def add_account(conn: sqlite3.Connection, **kw: Any) -> int:
    cur = conn.execute(
        """INSERT INTO account (label, email, login, vault_ref, guard_note,
                                created_on, note)
           VALUES (:label, :email, :login, :vault_ref, :guard_note, :created_on, :note)""",
        {"created_on": today(), "login": None, "vault_ref": None,
         "guard_note": None, "note": None, **kw},
    )
    conn.commit()
    return int(cur.lastrowid)


def find_account(conn: sqlite3.Connection, label: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM account WHERE label = ?", (label,)).fetchone()


def set_status(conn: sqlite3.Connection, label: str, status: str) -> bool:
    cur = conn.execute("UPDATE account SET status = ? WHERE label = ?", (status, label))
    conn.commit()
    return cur.rowcount > 0


# ---------- เกมในไอดี ----------

def add_license(
    conn: sqlite3.Connection, account_id: int, appid: int, game_name: str | None,
    cost_baht: float | None, bought_on: str | None = None, note: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO license (account_id, appid, game_name, cost_baht, bought_on, note)
           VALUES (?,?,?,?,?,?)""",
        (account_id, appid, game_name, cost_baht, bought_on or today(), note),
    )
    conn.commit()
    return int(cur.lastrowid)


# ---------- การเช่า ----------

def open_rental(
    conn: sqlite3.Connection, account_id: int, days: int, *, appid: int | None = None,
    renter: str | None = None, contact: str | None = None,
    price_baht: float | None = None, starts_on: str | None = None,
    note: str | None = None,
) -> tuple[int, str]:
    start = starts_on or today()
    end = (_d(start) + timedelta(days=days)).isoformat()
    cur = conn.execute(
        """INSERT INTO rental (account_id, appid, renter, contact, starts_on, ends_on,
                               price_baht, note)
           VALUES (?,?,?,?,?,?,?,?)""",
        (account_id, appid, renter, contact, start, end, price_baht, note),
    )
    conn.commit()
    return int(cur.lastrowid), end


def busy_rental(
    conn: sqlite3.Connection, account_id: int, on: str | None = None
) -> sqlite3.Row | None:
    """การเช่าที่ยังค้างของไอดีนี้ — ยังไม่คืน และวันที่อ้างอิงยังอยู่ในช่วงเช่า"""
    d = on or today()
    return conn.execute(
        """SELECT * FROM rental
           WHERE account_id = ? AND returned_on IS NULL
             AND starts_on <= ? AND ends_on > ?
           ORDER BY starts_on DESC LIMIT 1""",
        (account_id, d, d),
    ).fetchone()


def overdue_rentals(conn: sqlite3.Connection, on: str | None = None) -> list[sqlite3.Row]:
    """เลยกำหนดคืนแล้วแต่ยังไม่ได้ปิด — ต้องทวงหรือลืมกดปิด อย่างใดอย่างหนึ่ง"""
    d = on or today()
    return conn.execute(
        """SELECT r.*, a.label FROM rental r JOIN account a ON a.id = r.account_id
           WHERE r.returned_on IS NULL AND r.ends_on <= ?
           ORDER BY r.ends_on""",
        (d,),
    ).fetchall()


def close_rental(conn: sqlite3.Connection, rental_id: int, on: str | None = None) -> bool:
    cur = conn.execute(
        "UPDATE rental SET returned_on = ? WHERE id = ? AND returned_on IS NULL",
        (on or today(), rental_id),
    )
    conn.commit()
    return cur.rowcount > 0


# ---------- สรุป ----------

def account_overview(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """ไอดีทุกตัว + เกมที่อยู่ในนั้น + สถานะว่าง/ติดเช่า"""
    out = []
    for a in conn.execute("SELECT * FROM account ORDER BY label"):
        games = conn.execute(
            "SELECT appid, game_name, cost_baht FROM license "
            "WHERE account_id = ? ORDER BY bought_on",
            (a["id"],),
        ).fetchall()
        agg = conn.execute(
            "SELECT COALESCE(SUM(price_baht), 0) AS revenue, COUNT(*) AS n "
            "FROM rental WHERE account_id = ?",
            (a["id"],),
        ).fetchone()
        out.append({
            "row": a,
            "games": games,
            "cost": sum((g["cost_baht"] or 0) for g in games),
            "revenue": agg["revenue"],
            "rentals": agg["n"],
            "busy": busy_rental(conn, a["id"]),
        })
    return out


def per_game(conn: sqlite3.Connection, window_days: int = 30) -> dict[int, dict[str, Any]]:
    """สรุปรายเกม: ทุน · รายได้ · สัดส่วนวันที่ปล่อยเช่าออกได้จริงในหน้าต่างล่าสุด

    **utilization คือดีมานด์ของจริง** ต่างจาก stocked_total ใน radar ที่วัดซัพพลาย
    (คู่แข่งมีของกี่ใบ ซึ่งอาจเป็นของค้างสต็อกก็ได้ — UPDATE.md 3.3)

    วันพร้อมปล่อยนับจาก *วันที่ซื้อเกม* ไม่ใช่จากต้นหน้าต่างเสมอ ไม่งั้นเกมที่เพิ่ง
    ซื้อเมื่อวานจะได้ utilization ต่ำเตี้ยเพราะ 29 วันแรกที่ยังไม่มีของถูกนับเป็น
    วันที่ปล่อยไม่ออก
    """
    w_end = _d(today())
    w_start = w_end - timedelta(days=window_days)
    games: dict[int, dict[str, Any]] = {}

    def slot(appid: int, name: str | None) -> dict[str, Any]:
        g = games.setdefault(appid, {
            "appid": appid, "name": name, "copies": 0, "cost": 0.0,
            "revenue": 0.0, "rentals": 0, "days_avail": 0, "days_rented": 0,
        })
        if not g["name"]:
            g["name"] = name
        return g

    for lic in conn.execute("SELECT * FROM license"):
        g = slot(lic["appid"], lic["game_name"])
        g["copies"] += 1
        g["cost"] += lic["cost_baht"] or 0
        avail_from = max(_d(lic["bought_on"]), w_start)
        g["days_avail"] += max(0, (w_end - avail_from).days)

    for r in conn.execute("SELECT * FROM rental WHERE appid IS NOT NULL"):
        # เช่าเกมที่ไม่มี license บันทึกไว้ก็ยังต้องนับรายได้ ไม่ใช่ทิ้งเงียบ ๆ
        g = slot(r["appid"], None)
        g["revenue"] += r["price_baht"] or 0
        g["rentals"] += 1
        lo = max(_d(r["starts_on"]), w_start)
        hi = min(_d(r["ends_on"]), w_end)
        g["days_rented"] += max(0, (hi - lo).days)

    for g in games.values():
        g["utilization"] = g["days_rented"] / g["days_avail"] if g["days_avail"] else None
        g["roi"] = (g["revenue"] / g["cost"]) if g["cost"] else None
    return games


def export_csv(conn: sqlite3.Connection, out_dir: Path) -> list[Path]:
    """เขียนทุกตารางเป็น CSV — สำรองข้อมูล/เปิดใน Excel

    **ไฟล์ที่ได้มีอีเมลและชื่อลูกค้า** อย่าเขียนลงในโฟลเดอร์ที่ git ตามอยู่
    """
    import csv

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for table in ("account", "license", "rental"):
        cur = conn.execute(f"SELECT * FROM {table}")
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        path = out_dir / f"{table}.csv"
        # utf-8-sig เพราะ Excel บน Windows อ่าน utf-8 เปล่า ๆ เป็นภาษาไทยเพี้ยน
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(cols)
            wr.writerows(tuple(r) for r in rows)
        written.append(path)
    return written
