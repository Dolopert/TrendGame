"""ร้านเรา (หลังบ้าน 499k) — สถานะไอดี · ยอดเช่า · ประวัติรายการ

**ฐานข้อมูลคนละไฟล์กับ radar.sqlite3 โดยเจตนา** — เหตุผลเดียวกับ stock.py:
`data/radar.sql` ถูก dump ขึ้น repo สาธารณะทุกคืน 22:00 ถ้ายอดเงินร้านเราหลุดเข้าไป
คู่แข่งที่อ่าน repo เห็นหมด ข้อมูลชุดนี้จึงอยู่ที่ `data/own.sqlite3`
(gitignore ผ่าน `data/*.sqlite3`) และ **ไม่มีคำสั่ง dump** ให้เผลอใช้
หน้าแสดงผลเขียนลง `out/own.html` ซึ่ง `out/` โดน ignore อยู่แล้วเช่นกัน

**ทำไมต้องดึงผ่านเบราว์เซอร์**: API หลังบ้าน (/dashboard) อยู่หลัง Cloudflare
ที่ให้ผล 502 กับ client ที่ไม่ใช่เบราว์เซอร์จริง (curl/httpx เจอแล้ว 5 ก.ย. 2026)
แม้ส่ง cookie ครบ — ส่วน API สาธารณะ (getGameList ที่ market.py ใช้) ยังยิงตรงได้
การดึงจึงใช้เบราว์เซอร์ SyncProfile Brave ที่ login 499k ค้างอยู่ (พอร์ต 9222)
รัน `fetch()` ในหน้าเว็บผ่าน CDP — ไม่มีการเก็บคุกกี้/รหัสลงไฟล์เลย

**ห้ามเก็บของพวกนี้เด็ดขาด**: ฟิลด์ `password`/`username` ที่ API
getrentalaccount คืนมาเป็นของไอดี Steam ของร้าน — ตัดทิ้งก่อนเข้าฐานทุกครั้ง
(ไฟล์ HTML ที่ generate ก็ไม่มีการันตีความปลอดภัย อย่าใส่ของลับ)

session token ของ 499k หมดอายุทุก ~3 วัน → ถ้าเจอ redirect ไป /user/sign-in
จะ raise MineAuthExpired ให้ผู้เรียกเตือน user ให้ re-login (เปิดหน้า login
ใน SyncProfile Brave แล้วให้ user พิมพ์เอง — session Google ยังอยู่ → 1 คลิก)
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CDP_HTTP = "http://127.0.0.1:9222"
DASH_URL = "https://store.499k-network.com/dashboard"
API_BASE = "https://store.499k-network.com"

TH = timezone(timedelta(hours=7))

SCHEMA = """
CREATE TABLE IF NOT EXISTS summary_snapshot (
    taken_at       TEXT PRIMARY KEY,      -- UTC ISO
    month          INTEGER NOT NULL,      -- เดือนที่ query (ไทย, 1-12)
    year           INTEGER NOT NULL,      -- ปีที่ query (ค.ศ.)
    ongoing_profit REAL,                  -- ยอดเช่าที่กำลังดำเนินการ
    expired_profit REAL,                  -- ยอดที่จบแล้วยังไม่ถอน
    amount_all     REAL, fee_all REAL, income_all REAL,
    amount_today   REAL, fee_today REAL, income_today REAL,
    amount_month   REAL, fee_month REAL, income_month REAL
);

-- สถานะไอดี ณ เวลาหนึ่ง — เก็บทุกครั้งที่ดึง (snapshot รายวัน)
CREATE TABLE IF NOT EXISTS account_snapshot (
    taken_at            TEXT NOT NULL,
    platform_account_id INTEGER NOT NULL, -- id ไอดีบนแพลตฟอร์ม
    status              TEXT,             -- available | (ถูกเช่า/อื่น ๆ ตามแพลตฟอร์ม)
    game_names          TEXT,             -- เกมในไอดี คั่นด้วย ,
    total_rentals       INTEGER,
    total_revenue       REAL,
    profit              REAL,
    PRIMARY KEY (taken_at, platform_account_id)
);

-- ประวัติรายการเช่า/เงิน — upsert ด้วย transaction_id ของแพลตฟอร์ม
-- (สถานะเปลี่ยนได้: waiting -> จบ/คืนเงิน ฯลฯ — ดึงซ้ำแล้วค่อยแก้แถวเดิม)
-- ชื่อ txn ไม่ใช่ transaction เพราะ transaction เป็นคำสงวนของ SQLite
CREATE TABLE IF NOT EXISTS txn (
    transaction_id     INTEGER PRIMARY KEY,
    rental_order_id    INTEGER,
    amount             REAL,              -- ยอดที่ลูกค้าจ่าย
    fee                REAL,              -- ค่าธรรมเนียมแพลตฟอร์ม (20%)
    profit             REAL,              -- กำไร = amount - fee
    product_type       TEXT,
    rental_status      TEXT,              -- waiting = กำลังเช่า
    seller_claim_status TEXT,
    transaction_date   TEXT,              -- UTC ISO จากแพลตฟอร์ม
    start_at           TEXT,
    end_at             TEXT,
    bundle_name        TEXT,
    first_seen         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
"""


class MineUnavailable(RuntimeError):
    """เชื่อม CDP/เบราว์เซอร์ไม่ได้ — ยังดึงได้เมื่อเปิด Hermes (Brave 9222)"""


class MineAuthExpired(RuntimeError):
    """session 499k หมดอายุ — ต้องให้ user re-login ใน SyncProfile Brave"""


def connect(path: Path | str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA)
    return conn


# ---------- CDP ----------

def _http_json(path: str, method: str = "GET") -> Any:
    req = urllib.request.Request(CDP_HTTP + path, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _ws_eval(ws_url: str, js: str, timeout: float = 90) -> str:
    """รัน JS ในหน้า ผ่าน CDP websocket แล้วคืน return value (string)"""
    import websocket  # noqa: PLC0415 — import เฉพาะเมื่อใช้จริง

    ws = websocket.create_connection(ws_url, timeout=timeout)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True, "awaitPromise": True},
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                if "error" in msg:
                    raise MineUnavailable(f"CDP error: {msg['error']}")
                return msg["result"].get("result", {}).get("value")
    finally:
        ws.close()


def _wait_ready(ws_url: str, timeout: float = 25) -> bool:
    """รอหน้าโหลดเสร็จ คืน True ถ้าจบที่หน้า login (session หมดอายุ)"""
    import websocket  # noqa: PLC0415

    ws = websocket.create_connection(ws_url, timeout=timeout + 5)
    try:
        seq = 0
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            seq += 1
            ws.send(json.dumps({
                "id": seq,
                "method": "Runtime.evaluate",
                "params": {"expression": "JSON.stringify({u: location.href, r: document.readyState})",
                           "returnByValue": True},
            }))
            state = None
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == seq:
                    state = json.loads(msg["result"]["result"]["value"])
                    break
            if state.get("r") == "complete":
                time.sleep(2.0)  # ให้ SPA/NextAuth redirect จัดการต่อให้เรียบร้อย
                return state["u"].startswith("https://store.499k-network.com/user/sign-in")
            time.sleep(0.8)
        return False  # timeout — ปล่อยให้ FETCH_JS จัดการเอง (มันเช็ค sign-in อีกชั้น)
    finally:
        ws.close()


def _close_target(ws_url: str) -> None:
    import websocket  # noqa: PLC0415

    ws = websocket.create_connection(ws_url, timeout=15)
    try:
        ws.send(json.dumps({"id": 1, "method": "Page.close"}))
        ws.recv()
    finally:
        ws.close()


FETCH_JS = """
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 30 && document.readyState !== 'complete'; i++) await sleep(300);
  if (location.pathname.startsWith('/user/sign-in')) {
    return JSON.stringify({auth: 'expired', url: location.href});
  }
  const out = {auth: 'ok', url: location.href};
  const get = async (p) => {
    const r = await fetch(API_BASE + '/' + p, {
      credentials: 'include', headers: {Accept: 'application/json'},
    });
    return {s: r.status, b: await r.text()};
  };
  try {
    const d = await get('api/product/steam/rental/storeDashboard?sold_month=' + MONTH + '&sold_year=' + YEAR);
    out.dash = d;
    if (d.s === 401 || /Unauthorized/.test(d.b.slice(0, 200))) {
      return JSON.stringify({auth: 'expired', url: location.href});
    }
    try {
      let page = 1, all = [], pg = {totalPages: 1};
      do {
        const r = await get('api/product/steam/rental/getrentalaccount?page=' + page
                             + '&keyword=&sort_field=id&sort_order=desc');
        if (r.s !== 200) break;
        const j = JSON.parse(r.b);
        all = all.concat(j.accounts || []);
        pg = j.pagination || {};
        page += 1;
      } while (page <= (pg.totalPages || 1));
      out.accounts = JSON.stringify(all);
    } catch (e) { out.accounts = 'ERR ' + (e && e.message || e); }
    try {
      let tpage = 1, all = [], pg = {totalPages: 1};
      do {
        const r = await get('api/product/steam/rental/gettransactions?page=1&keyword=&trans_page='
                             + tpage + '&sold_month=&sold_year=&type=all');
        if (r.s !== 200) break;
        const j = JSON.parse(r.b);
        const rows = j.transactions || [];
        all = all.concat(rows);
        pg = j.transaction_pagination || {};
        if (!rows.length) break;
        tpage += 1;
      } while (tpage <= (pg.totalPages || 1));
      out.transactions = JSON.stringify(all);
    } catch (e) { out.transactions = 'ERR ' + (e && e.message || e); }
  } catch (e) { out.fatal = String(e && e.message || e); }
  return JSON.stringify(out);
})()
"""


def seller_fetch() -> dict[str, Any]:
    """ดึง dash + ไอดี + รายการเงินจากหลังบ้าน ผ่านเบราว์เซอร์ CDP พอร์ต 9222

    คืน dict {dash, accounts, transactions} ที่ **ตัด password/username ออกแล้ว**
    ต้องมี SyncProfile Brave รันอยู่ (Hermes/iLearning cron เป็นคนเปิดให้)
    เปิดแท็บใหม่ทุกครั้ง (สภาพ deterministic) แล้วปิดทิ้งหลังดึงเสร็จ
    """
    import urllib.parse  # noqa: PLC0415

    try:
        pages = _http_json("/json/list")
    except Exception as e:
        raise MineUnavailable(
            f"ต่อ CDP (พอร์ต 9222) ไม่ได้: {e} — ต้องเปิด Hermes/เบราว์เซอร์ SyncProfile "
            "ให้รันอยู่ก่อน ถึงจะดึงหลังบ้าน 499k ได้"
        ) from e

    # เก็บกวาดแท็บ 499k ที่ค้างจากรอบก่อน (รวมของที่ดึงค้าง) แล้วเปิดใหม่
    for p in pages:
        if p.get("type") == "page" and p.get("url", "").startswith("https://store.499k-network.com"):
            try:
                _http_json("/json/close/" + p["id"])
            except Exception:
                pass

    opened = None
    try:
        opened = _http_json("/json/new?" + urllib.parse.quote(DASH_URL, safe=""), method="PUT")
    except Exception:
        opened = _http_json("/json/new?" + urllib.parse.quote(DASH_URL, safe=""))
    ws_url = opened["webSocketDebuggerUrl"]

    # รอให้หน้าโหลดจริงและพ้นหน้า login (NextAuth อาจ redirect ไปมาไม่กี่จังหวะ)
    expired = _wait_ready(ws_url)
    if expired:
        raise MineAuthExpired(
            "session 499k หมดอายุ (เจอหน้า login) — ให้ user เปิด "
            f"{DASH_URL} ใน SyncProfile Brave แล้วล็อกอินใหม่ (Google = 1 คลิก)"
        )

    now = datetime.now(TH)
    js = (
        FETCH_JS.replace("API_BASE", json.dumps(API_BASE))
        .replace("MONTH", str(now.month))
        .replace("YEAR", str(now.year))
    )
    try:
        raw = _ws_eval(ws_url, js)
    finally:
        try:
            _close_target(ws_url)
        except Exception:
            pass  # ปิดไม่ได้ก็ไม่เป็นไร — รอบหน้าจะเก็บกวาดแท็บค้างให้เอง

    try:
        data = json.loads(raw)
    except Exception:
        raise MineUnavailable(f"ผลจากเบราว์เซอร์ไม่ใช่ JSON: {raw[:200]!r}") from None

    if data.get("auth") == "expired":
        raise MineAuthExpired(
            "session 499k หมดอายุระหว่างดึง (เจอหน้า login) — ให้ user ล็อกอินใหม่ "
            f"ที่ {DASH_URL} ใน SyncProfile Brave (Google = 1 คลิก)"
        )
    if data.get("fatal"):
        raise MineUnavailable(f"fetch ในเบราว์เซอร์ล้ม: {data['fatal']}")

    def decode(key: str) -> list[dict[str, Any]]:
        v = data.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            if v.startswith("ERR "):
                raise MineUnavailable(f"{key}: {v}")
            try:
                return json.loads(v)
            except Exception:
                raise MineUnavailable(f"{key}: JSON ผิดปกติ: {v[:200]!r}") from None
        raise MineUnavailable(f"{key}: ไม่มีข้อมูล (คืน {v!r})")

    dash_raw = data.get("dash") or {}
    if dash_raw.get("s") != 200:
        raise MineUnavailable(f"storeDashboard คืน HTTP {dash_raw.get('s')}: {str(dash_raw.get('b'))[:200]}")

    dash = json.loads(dash_raw["b"])
    if not dash.get("status"):
        raise MineUnavailable(f"storeDashboard คืน status=false: {str(dash)[:200]}")

    accounts = decode("accounts")
    txs = decode("transactions")

    # ตัดของลับ/ไม่จำเป็นออก — password ของไอดี Steam ห้ามเก็บทุกกรณี
    clean_accounts = []
    for a in accounts:
        clean_accounts.append({
            "id": a.get("id"),
            "status": a.get("status"),
            "game_names": a.get("game_names"),
            "total_rentals": a.get("total_rentals"),
            "total_revenue": a.get("total_revenue"),
            "profit": a.get("profit"),
        })

    clean_txs = []
    for t in txs:
        amount = _num(t.get("amount"))
        profit = _num(t.get("profit", t.get("cost")))
        clean_txs.append({
            "transaction_id": t.get("transaction_id"),
            "rental_order_id": t.get("rental_order_id"),
            "amount": amount,
            "fee": round((amount - profit), 2) if amount is not None and profit is not None else None,
            "profit": profit,
            "product_type": t.get("product_type"),
            "rental_status": t.get("rental_status"),
            "seller_claim_status": t.get("seller_claim_status"),
            "transaction_date": t.get("transaction_date"),
            "start_at": t.get("start_at"),
            "end_at": t.get("end_at"),
            "bundle_name": t.get("bundle_name"),
        })

    return {"dash": dash, "accounts": clean_accounts, "transactions": clean_txs}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- บันทึก ----------

def save_pull(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, int]:
    """เขียนผล seller_fetch หนึ่งรอบลงฐาน เรียกใน transaction เดียว"""
    taken = utcnow()
    dash = data["dash"]
    now = datetime.now(TH)
    conn.execute(
        """
        INSERT OR REPLACE INTO summary_snapshot
            (taken_at, month, year, ongoing_profit, expired_profit,
             amount_all, fee_all, income_all, amount_today, fee_today, income_today,
             amount_month, fee_month, income_month)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (taken, now.month, now.year,
         dash.get("ongoing_profit"), dash.get("expired_profit"),
         dash.get("amount_all"), dash.get("fee_all"), dash.get("income_all"),
         dash.get("amount_today"), dash.get("fee_today"), dash.get("income_today"),
         dash.get("amount_month"), dash.get("fee_month"), dash.get("income_month")),
    )
    for a in data["accounts"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO account_snapshot
                (taken_at, platform_account_id, status, game_names,
                 total_rentals, total_revenue, profit)
            VALUES (?,?,?,?,?,?,?)
            """,
            (taken, a["id"], a["status"], a["game_names"],
             a["total_rentals"], a["total_revenue"], a["profit"]),
        )
    for t in data["transactions"]:
        conn.execute(
            """
            INSERT OR REPLACE INTO txn
                (transaction_id, rental_order_id, amount, fee, profit, product_type,
                 rental_status, seller_claim_status, transaction_date, start_at, end_at,
                 bundle_name, first_seen, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (t["transaction_id"], t["rental_order_id"], t["amount"], t["fee"], t["profit"],
             t["product_type"], t["rental_status"], t["seller_claim_status"],
             t["transaction_date"], t["start_at"], t["end_at"], t["bundle_name"],
             taken, taken),
        )
    conn.commit()
    return {
        "accounts": len(data["accounts"]),
        "transactions": len(data["transactions"]),
    }


# ---------- หน้าแสดงผล (local เท่านั้น — out/ โดน gitignore) ----------

def latest_summary(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM summary_snapshot ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.execute("SELECT * FROM summary_snapshot LIMIT 0").description]
    return dict(zip(cols, row))


def latest_accounts(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], str | None]:
    row = conn.execute(
        "SELECT taken_at FROM account_snapshot ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return [], None
    taken = row[0]
    rows = conn.execute(
        "SELECT * FROM account_snapshot WHERE taken_at = ? ORDER BY status, game_names",
        (taken,),
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM account_snapshot LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows], taken


def recent_transactions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM txn ORDER BY transaction_date DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM txn LIMIT 0").description]
    return [dict(zip(cols, r)) for r in rows]


def _th_date(iso: str | None) -> str:
    """UTC ISO จากแพลตฟอร์ม -> วันเดือนปีไทย (UTC+7)"""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TH)
    except ValueError:
        return iso[:16]
    return dt.strftime("%d/%m/%Y %H:%M")


def render_html(conn: sqlite3.Connection) -> str:
    """หน้า local สรุปสถานะร้านเรา — เนื้อหาอาจเป็นข้อมูลธุรกิจ ห้าม push ขึ้น public"""
    s = latest_summary(conn)
    accounts, taken = latest_accounts(conn)
    txs = recent_transactions(conn, 20)

    def b(v: Any) -> str:
        return "-" if v is None else f"{float(v):,.2f}"

    n_free = sum(1 for a in accounts if a.get("status") == "available")
    n_busy = len(accounts) - n_free

    cards = ""
    if s:
        cards = f"""
        <div class="cards">
          <div class="card"><div class="k">รายได้ทั้งหมด</div><div class="v">฿{b(s['income_all'])}</div></div>
          <div class="card"><div class="k">ยอดทั้งหมด (ก่อนหัก)</div><div class="v">฿{b(s['amount_all'])}</div></div>
          <div class="card"><div class="k">ค่าธรรมเนียมรวม</div><div class="v">฿{b(s['fee_all'])}</div></div>
          <div class="card"><div class="k">เดือนนี้ {s['month']}/{s['year']}</div><div class="v">฿{b(s['income_month'])}</div></div>
          <div class="card"><div class="k">วันนี้</div><div class="v">฿{b(s['income_today'])}</div></div>
          <div class="card"><div class="k">กำลังเช่า / จบแล้ว</div><div class="v">฿{b(s['ongoing_profit'])} / ฿{b(s['expired_profit'])}</div></div>
        </div>"""

    acc_rows = "".join(
        f"<tr><td>{a['platform_account_id']}</td><td>{a['game_names'] or '-'}</td>"
        f"<td>{'ว่าง' if a.get('status') == 'available' else a.get('status') or '-'}</td>"
        f"<td>{a.get('total_rentals') or 0}</td><td>฿{b(a.get('total_revenue'))}</td>"
        f"<td>฿{b(a.get('profit'))}</td></tr>"
        for a in accounts
    )

    status_th = {
        "waiting": "กำลังเช่า", "success": "สำเร็จ", "expired": "จบ", "cancel": "ยกเลิก",
    }
    tx_rows = "".join(
        f"<tr><td>{t['transaction_id']}</td><td>{_th_date(t.get('start_at'))}</td>"
        f"<td>฿{b(t.get('amount'))}</td><td>฿{b(t.get('fee'))}</td><td>฿{b(t.get('profit'))}</td>"
        f"<td>{status_th.get(t.get('rental_status') or '', t.get('rental_status') or '-')}</td></tr>"
        for t in txs
    )

    updated = _th_date(taken) if taken else "-"
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<title>ร้านเรา — 499k (local)</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #e6edf3;
         margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; }} h2 {{ font-size: 15px; margin-top: 28px; color: #9aa4b2; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
           padding: 12px 16px; min-width: 150px; }}
  .k {{ font-size: 12px; color: #9aa4b2; }} .v {{ font-size: 18px; font-weight: 600; margin-top: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }}
  th, td {{ border-bottom: 1px solid #21262d; padding: 6px 8px; text-align: left; }}
  th {{ color: #9aa4b2; font-weight: 500; }}
  .note {{ color: #8b949e; font-size: 12px; margin-top: 24px; }}
</style></head><body>
<h1>ร้านเรา — หลังบ้าน 499k · Online101Gaming</h1>
<div class="note">อัปเดตล่าสุด {updated} · ไอดี {n_free} ว่าง / {n_busy} ไม่ว่าง</div>
{cards}
<h2>ไอดี ({len(accounts)})</h2>
<table><tr><th>id</th><th>เกม</th><th>สถานะ</th><th>เช่าครั้ง</th><th>รายได้รวม</th><th>กำไรรวม</th></tr>
{acc_rows}</table>
<h2>รายการล่าสุด ({len(txs)})</h2>
<table><tr><th>#</th><th>เริ่มเช่า</th><th>ยอด</th><th>ค่าธรรมเนียม</th><th>กำไร</th><th>สถานะ</th></tr>
{tx_rows}</table>
<div class="note">หน้าสรุปเฉพาะเครื่อง — ข้อมูลธุรกิจของร้าน ห้าม push ขึ้นที่สาธารณะ · รหัสผ่านไอดีไม่ถูกเก็บในระบบนี้</div>
</body></html>"""
