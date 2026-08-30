"""Phase 0 — ตรวจว่า API ของ 499k ให้ข้อมูลพอจะเอามาใช้กับเรดาร์ได้จริงไหม

สคริปต์ชั่วคราว ใช้ครั้งเดียวเพื่อตัดสินใจว่าคุ้มลงแรง Phase 1 ไหม
ผ่านแล้วลบทิ้งได้ ตรรกะที่ได้ผลค่อยย้ายไป src/game_radar/rental_api.py

**อ่านอย่างเดียว — เรียกแต่ GET** ไม่แตะ POST /orders, /activate, /renew
ซึ่งตัดเงินจริงจากบัญชี เครื่องมือนี้มีไว้วิเคราะห์ ไม่ใช่สั่งซื้อ

รัน:  uv run --project game-radar python probe_499k_api.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = "https://store.499k-network.com/api/v1"
PAUSE = 1.1          # จำกัด 60 ครั้ง/นาที — เว้น 1.1 วิ ปลอดภัยกว่าไปชนเพดาน


def load_env() -> dict[str, str]:
    """อ่าน .env แบบง่าย ๆ ไม่เพิ่ม dependency ให้โปรเจกต์ที่มี dep เดียว"""
    out: dict[str, str] = {}
    p = ROOT / ".env"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get(client: httpx.Client, path: str, **params):
    """คืน (data, error) — error เป็น dict {code,message} ตาม envelope ของเขา"""
    for _ in range(3):
        r = client.get(f"{BASE}{path}", params=params or None)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "5"))
            print(f"      โดน rate limit รอ {wait} วิ")
            time.sleep(wait)
            continue
        try:
            j = r.json()
        except ValueError:
            return None, {"code": f"HTTP_{r.status_code}", "message": r.text[:120]}
        time.sleep(PAUSE)
        if j.get("success"):
            return j.get("data"), None
        return None, (j.get("error") or {"code": "UNKNOWN", "message": ""})
    return None, {"code": "RATE_LIMITED", "message": "ลองสามครั้งแล้วยังโดนจำกัด"}


def scraped_baseline() -> dict[int, int]:
    """สต็อกรายเกมจาก scraper ปัจจุบัน ใช้เป็นตัวเทียบว่า API เห็นครบไหม"""
    db = ROOT / "data" / "radar.sqlite3"
    if not db.exists():
        return {}
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select max(taken_at) t from market_snapshot where scope='platform'"
    ).fetchone()
    if not row or not row["t"]:
        return {}
    return {r["appid"]: r["n"] for r in conn.execute(
        "select appid, sum(id_count) n from market_snapshot "
        "where scope='platform' and taken_at=? group by appid", (row["t"],))}


def pick_unstocked(base: dict[int, int]) -> list[tuple[int, str]]:
    """เกมที่เรดาร์บอกว่าน่าซื้อแต่ยังไม่มีใครสต็อก — ของที่เราอยากถามที่สุด"""
    db = ROOT / "data" / "radar.sqlite3"
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out: list[tuple[int, str]] = []
    for r in conn.execute(
        "select appid, name from title where is_coop=1 and coming_soon=0 "
        "and price_final is not null order by appid"
    ):
        if r["appid"] not in base:
            out.append((r["appid"], r["name"]))
        if len(out) >= 3:
            break
    return out


def verdict(topup_ok, coverage_ok, unstocked_ok) -> None:
    def mark(v):
        return "ผ่าน" if v is True else ("ไม่ผ่าน" if v is False else "ตอบไม่ได้")

    print("\n" + "=" * 66)
    print("สรุป")
    print(f"  1. คีย์จริง + ยอดเติมถึงขั้นต่ำ       {mark(topup_ok)}")
    print(f"  2. availability เห็นไอดีครบทุกร้าน   {mark(coverage_ok)}")
    print(f"  3. ถามเกมที่ยังไม่มีใครสต็อกได้       {mark(unstocked_ok)}")
    print()
    if topup_ok and coverage_ok:
        print("  -> ไปต่อ Phase 1 ได้ (เก็บ utilization)")
    elif topup_ok and coverage_ok is False:
        print("  -> ไปต่อได้ แต่ต้องระบุขอบเขตข้อมูลให้ชัด ไม่งั้น utilization จะเอนเอียง")
    else:
        print("  -> ยังไปต่อไม่ได้ ดูสาเหตุข้างบน")
    print("=" * 66)


def main() -> int:
    key = load_env().get("API_KEY_499K", "").strip()
    if not key:
        print("ไม่พบ API_KEY_499K ใน game-radar/.env")
        print("คัดลอก .env.example เป็น .env แล้วใส่คีย์ (ไฟล์นี้ถูก gitignore แล้ว)")
        return 2

    sandbox = key.startswith("499k_test_")
    print("=" * 66)
    print("Phase 0 — ตรวจความสามารถของ API 499k")
    print(f"โหมด: {'SANDBOX (คีย์ทดสอบ)' if sandbox else 'LIVE (คีย์จริง)'}")
    if sandbox:
        print()
        print("  ! คีย์ทดสอบเห็นแค่สินค้าจำลอง 1 ตัว (product_id 999001)")
        print("    ข้อ 2 กับ 3 จะตอบไม่ได้ ต้องใช้คีย์ 499k_live_ เท่านั้น")
    print("=" * 66)

    client = httpx.Client(
        timeout=30.0,
        headers={"Authorization": f"Bearer {key}",
                 "Accept": "application/json",
                 "User-Agent": "game-radar/0.2 (research)"},
    )

    # ---------- ข้อ 1 ----------
    print("\n[1/3] คีย์ใช้ได้ไหม และผ่านเงื่อนไขยอดเติมขั้นต่ำหรือยัง")
    me, err = get(client, "/me")
    if err:
        print(f"  ไม่ผ่าน — {err['code']}: {err['message']}")
        if err["code"] == "MIN_TOPUP_REQUIRED":
            print("    ยอดเติมสะสมยังไม่ถึงขั้นต่ำ (เดิม 885 จาก 2,000)")
        verdict(False, None, None)
        return 1
    topup = me.get("min_topup") or {}
    print(f"  คีย์ใช้ได้ — {me.get('key_prefix')} · สถานะ {me.get('client', {}).get('status')}")
    print(f"    ยอดเงิน {me.get('balance')} · ซื้อสะสม {me.get('volume')} · เรท {me.get('rate_percent')}%")
    print(f"    ยอดเติมขั้นต่ำ {topup.get('current')}/{topup.get('required')} "
          f"-> {'ผ่าน' if topup.get('passed') else 'ยังไม่ผ่าน'}")

    # ---------- ข้อมูลประกอบ ----------
    print("\n[ข้อมูลประกอบ] สินค้าที่ API เปิดให้เห็น")
    prods, err = get(client, "/products")
    if err:
        print(f"  ดึงรายการสินค้าไม่ได้ — {err['code']}: {err['message']}")
        verdict(topup.get("passed"), None, None)
        return 1
    items = prods.get("products", [])
    types = prods.get("types", [])
    by_type: dict[str, int] = {}
    for p in items:
        t = p.get("type", "?")
        by_type[t] = by_type.get(t, 0) + 1
    print(f"  รวม {prods.get('total')} รายการ · types ที่ระบบบอก = {types}")
    print(f"  แยกตาม type: {by_type}")

    base = scraped_baseline()
    print(f"  scraper เห็นตลาดเช่า {len(base)} เกม "
          f"({sum(base.values())} ไอดี) ใช้เป็นตัวตั้ง")

    if sandbox:
        print("\n[2/3] [3/3] ข้ามทั้งสองข้อ — คีย์ทดสอบตอบไม่ได้")
        verdict(topup.get("passed"), None, None)
        return 0

    # ---------- ข้อ 2 ----------
    print("\n[2/3] availability เห็นไอดีครบทุกร้านไหม")
    print("      scraper อ่านจากหน้าร้านสาธารณะ = เห็นทุกร้าน จึงใช้เป็นตัวตั้ง")
    targets = sorted(base.items(), key=lambda kv: -kv[1])[:6]
    rows = []
    for appid, scraped_n in targets:
        data, e = get(client, f"/products/{appid}/availability")
        if e:
            rows.append([appid, scraped_n, None, e["code"]])
        else:
            rows.append([appid, scraped_n, len(data.get("accounts", [])),
                         data.get("name", "")])
    print(f"\n  {'appid':>8} {'scraper':>8} {'API':>5}  หมายเหตุ")
    for appid, s_n, a_n, note in rows:
        print(f"  {appid:>8} {s_n:>8} {str(a_n if a_n is not None else '-'):>5}  {note}")
    got = [r for r in rows if r[2] is not None]
    full = [r for r in got if r[2] >= r[1]]
    coverage_ok = None
    if not got:
        print("\n  เรียก availability ไม่ได้เลยสักเกม")
        coverage_ok = False
    elif len(full) == len(got):
        print(f"\n  API เห็นไอดีไม่น้อยกว่าที่ scraper เห็น ทั้ง {len(got)} เกม")
        coverage_ok = True
    else:
        print(f"\n  เห็นครบ {len(full)}/{len(got)} เกม — ครอบคลุมไม่เต็ม")
        coverage_ok = False

    # ---------- ข้อ 3 ----------
    print("\n[3/3] ถาม availability ของเกมที่ยังไม่มีใครสต็อกได้ไหม")
    print("      ได้ = ใช้หาช่องว่างได้ · 404 = ใช้ได้แค่กับเกมที่มีของอยู่แล้ว")
    unstocked_ok = None
    picks = pick_unstocked(base)
    for appid, name in picks:
        data, e = get(client, f"/products/{appid}/availability")
        if e:
            print(f"  {appid} {name[:30]:30s} -> {e['code']}")
            if unstocked_ok is None:
                unstocked_ok = False
        else:
            print(f"  {appid} {name[:30]:30s} -> ได้ ({len(data.get('accounts', []))} ไอดี)")
            unstocked_ok = True
    if not picks:
        print("  หาเกมที่ยังไม่มีใครสต็อกในฐานข้อมูลไม่ได้")

    verdict(topup.get("passed"), coverage_ok, unstocked_ok)

    (ROOT / "probe_499k_result.json").write_text(
        json.dumps({"sandbox": sandbox, "types": types, "by_type": by_type,
                    "coverage": rows, "unstocked_ok": unstocked_ok},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nบันทึกผลดิบไว้ที่ probe_499k_result.json (อย่า commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
