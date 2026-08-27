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
                "in_coop_topsellers": 0,
                "in_coop_upcoming": 0,
                "in_coop_new": 0,
                "coop_topsellers_rank": None,
                "coop_upcoming_rank": None,
                "coop_new_rank": None,
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

        if verbose:
            print("[3.5/4] ค้นเกม co-op (ขายดี / กำลังมา / เพิ่งออก) ...", flush=True)
        for bucket in steam.COOP_BUCKETS:
            for pos, (appid, name) in enumerate(
                steam.search_coop(client, bucket, pages=2, cc=cc), start=1
            ):
                s = slot(appid)
                s[f"in_{bucket}"] = 1
                s[f"{bucket}_rank"] = pos
                names.setdefault(appid, name)

        # เกมที่ยังไม่รู้ CCU ต้องยิงทีละตัว
        # เกมที่ยังไม่วางขายจะไม่มี CCU อยู่แล้ว ข้ามไปเลยเพื่อไม่ยิงเปล่า
        missing = [
            a
            for a, s in rows.items()
            if s["ccu"] is None and not s["in_coop_upcoming"]
        ]
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
            else:
                # จำไว้ว่าเคยลองแล้วไม่ได้ จะได้ไม่ยิงซ้ำทุกรอบตลอดไป
                db.mark_metadata_failed(conn, appid)
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


def run_market_scan(conn: sqlite3.Connection, verbose: bool = True) -> dict[str, Any]:
    """เก็บสต็อกของตลาดเช่าหนึ่งรอบ — เบามาก ยิงไม่กี่ request

    ควรรันทุกวัน แม้วันที่ไม่ได้สแกน Steam เพราะคุณค่าของตารางนี้อยู่ที่
    ความต่อเนื่อง ไม่ใช่ความละเอียด ขาดไปวันหนึ่งคือเสียจุดเปรียบเทียบไปหนึ่งจุด
    """
    from . import market

    taken_at = db.utcnow()
    with market._client() as client:
        platform = market.rental_market(client)
        mine = market.rental_own(client)

    n_p = db.insert_market(conn, taken_at, "platform", platform)
    n_m = db.insert_market(conn, taken_at, "mine", mine)
    conn.commit()

    total_p = sum(g.get("account_count", 0) for g in platform)
    total_m = sum(g.get("account_count", 0) for g in mine)
    if verbose:
        print(f"ตลาดทั้งแพลตฟอร์ม {n_p} เกม · {total_p} ไอดี")
        print(f"ร้านเรา            {n_m} เกม · {total_m} ไอดี "
              f"({total_m / total_p * 100:.1f}% ของตลาด)" if total_p else "")

    delta = db.market_delta(conn, "platform")
    moved = {k: v for k, v in delta.items() if v}
    if verbose and moved:
        names = {g["app_id"]: g["game_name"] for g in platform}
        print("\nสต็อกที่ขยับจากรอบก่อน:")
        for aid, d in sorted(moved.items(), key=lambda x: -abs(x[1]))[:10]:
            print(f"  {d:+3d} ใบ  {names.get(aid, aid)}")

    return {
        "taken_at": taken_at,
        "platform_games": n_p,
        "platform_accounts": total_p,
        "own_games": n_m,
        "own_accounts": total_m,
        "moved": len(moved),
        "market_scans": db.market_scan_count(conn),
    }
