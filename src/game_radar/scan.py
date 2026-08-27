"""การเก็บข้อมูลหนึ่งรอบ (one scan)

หนึ่งรอบ = หนึ่ง timestamp เดียวกันทั้งชุด เพื่อให้ snapshot เทียบกันได้ตรง ๆ
ลำดับการยิงถูกจัดให้ประหยัด request ที่สุด:
  1. ชาร์ต 2 ตัว  -> ได้ CCU + อันดับ ของ ~100-150 เกม ด้วย 2 request
  2. หน้าร้าน     -> ได้เกมใหม่/ลดราคาที่ยังไม่ติดชาร์ต ด้วย 1 request
  3. CCU รายตัว   -> เฉพาะเกมจากข้อ 3 ที่ไม่มีในชาร์ต
  4. appdetails   -> เฉพาะเกมที่ metadata เก่าหรือยังไม่เคยดึง (ตัวนี้ช้าสุด)
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from . import db, steam

APPDETAILS_DELAY = 1.5  # วินาที — Steam จำกัดราว 200 ครั้ง / 5 นาที


def run_scan(
    conn: sqlite3.Connection, cc: str = "th", metadata_limit: int = 250, verbose: bool = True
) -> dict[str, Any]:
    taken_at = db.utcnow()
    rows: dict[int, dict[str, Any]] = {}

    def slot(appid: int) -> dict[str, Any]:
        return rows.setdefault(
            appid,
            {
                "appid": appid,
                "ccu": None,
                "peak_in_game": None,
                "played_rank": None,
                "last_week_rank": None,
                "ccu_rank": None,
                "in_specials": 0,
                "in_new_releases": 0,
                "in_top_sellers": 0,
                "in_coming_soon": 0,
            },
        )

    with steam._client() as client:
        if verbose:
            print("[1/4] ชาร์ตคนเล่นเยอะสุดรายสัปดาห์ ...", flush=True)
        for r in steam.most_played(client):
            s = slot(r["appid"])
            s["played_rank"] = r.get("rank")
            s["last_week_rank"] = r.get("last_week_rank")
            s["peak_in_game"] = r.get("peak_in_game")

        if verbose:
            print("[2/4] ชาร์ตคนเล่นพร้อมกันตอนนี้ ...", flush=True)
        for r in steam.by_concurrent(client):
            s = slot(r["appid"])
            s["ccu"] = r.get("concurrent_in_game")
            s["ccu_rank"] = r.get("rank")
            s["peak_in_game"] = s["peak_in_game"] or r.get("peak_in_game")

        if verbose:
            print("[3/4] หน้าร้าน (ลดราคา / ใหม่ / ขายดี / กำลังมา) ...", flush=True)
        names: dict[int, str] = {}
        for bucket, items in steam.featured(client, cc=cc).items():
            for item in items:
                appid = item["id"]
                s = slot(appid)
                s[f"in_{bucket}"] = 1
                names[appid] = item.get("name") or f"app {appid}"

        # เกมจากหน้าร้านที่ไม่ติดชาร์ต ต้องยิง CCU ทีละตัว
        missing = [a for a, s in rows.items() if s["ccu"] is None]
        if verbose:
            print(f"      ยิง CCU รายตัวอีก {len(missing)} เกม ...", flush=True)
        for appid in missing:
            rows[appid]["ccu"] = steam.current_players(client, appid)

        for appid, s in rows.items():
            db.ensure_stub_title(conn, appid, names.get(appid, f"app {appid}"))
            db.insert_snapshot(conn, taken_at, s)
        conn.commit()

        stale = db.stale_appids(conn)[:metadata_limit]
        if verbose:
            print(f"[4/4] ดึงรายละเอียดเกม {len(stale)} ตัว (~{len(stale) * APPDETAILS_DELAY / 60:.1f} นาที) ...", flush=True)
        fetched = 0
        for i, appid in enumerate(stale, 1):
            data = steam.app_details(client, appid, cc=cc)
            if data:
                db.upsert_title(conn, appid, data)
                fetched += 1
            if i % 25 == 0:
                conn.commit()
                if verbose:
                    print(f"      {i}/{len(stale)}", flush=True)
            time.sleep(APPDETAILS_DELAY)
        conn.commit()

    return {
        "taken_at": taken_at,
        "titles_seen": len(rows),
        "metadata_fetched": fetched,
        "total_scans": db.scan_count(conn),
    }
