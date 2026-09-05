"""หน้าตาคำสั่ง

  game-radar scan      เก็บข้อมูลหนึ่งรอบ (รันวันละครั้งพอ)
  game-radar dash      สร้างหน้า dashboard จากข้อมูลที่มี
  game-radar top       ดูอันดับในเทอร์มินัลเร็ว ๆ
  game-radar run       scan แล้ว dash ต่อเลย
  game-radar stock     สต็อกไอดีของร้าน (ฐานข้อมูลแยก ไม่ขึ้น git)
  game-radar mine      ร้านเรา: ดึงสถานะไอดี+ยอดเช่าจากหลังบ้าน 499k (ฐานแยก ไม่ขึ้น git)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, mine, render, scan, stock
from .score import assess

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "radar.sqlite3"
DEFAULT_OUT = ROOT / "out" / "dashboard.html"
DEFAULT_SQL = ROOT / "data" / "radar.sql"
# คนละไฟล์กับ radar.sqlite3 เพราะในนี้มีอีเมลกับชื่อลูกค้า และ radar ถูก dump
# ขึ้น repo สาธารณะทุกคืน — ดูหัวไฟล์ stock.py
DEFAULT_STOCK_DB = ROOT / "data" / "stock.sqlite3"
# ฐานร้านเรา (หลังบ้าน 499k) — มีตัวเลขธุรกิจ ห้ามขึ้น repo public — ดูหัวไฟล์ mine.py
DEFAULT_OWN_DB = ROOT / "data" / "own.sqlite3"
DEFAULT_OWN_HTML = ROOT / "out" / "own.html"


def cmd_scan(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    result = scan.run_scan(
        conn,
        cc=args.cc,
        metadata_limit=args.metadata_limit,
        review_limit=args.review_limit,
    )
    print(
        f"\nเก็บแล้ว {result['titles_seen']} เกม "
        f"(รายละเอียดใหม่ {result['metadata_fetched']} · "
        f"รีวิวใหม่ {result['reviews_fetched']}) "
        f"— รวมเก็บมาทั้งหมด {result['total_scans']} รอบ"
    )
    return 0


def cmd_market(args: argparse.Namespace) -> int:
    from .market import MarketUnavailable

    conn = db.connect(Path(args.db))
    try:
        r = scan.run_market_scan(conn)
    except MarketUnavailable as e:
        # บน CI ไม่ควรให้ตลาดล่มไปหยุดการเก็บข้อมูล Steam ทั้งรอบ
        # ข้อมูลสองฝั่งเป็นอิสระต่อกัน ขาดฝั่งหนึ่งยังดีกว่าขาดทั้งคู่
        print(f"ดึงข้อมูลตลาดไม่ได้: {e}", file=sys.stderr)
        if args.allow_fail:
            print("ข้ามไปก่อนตามที่สั่ง (--allow-fail)", file=sys.stderr)
            return 0
        return 1
    print(f"\nเก็บสต็อกตลาดมาแล้วทั้งหมด {r['market_scans']} รอบ")
    if r["market_scans"] < 2:
        print("(ต้องมีอย่างน้อย 2 รอบถึงจะเห็นว่าสต็อกขยับไปทางไหน)")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    n = db.dump_sql(conn, Path(args.sql))
    size = Path(args.sql).stat().st_size
    print(f"เขียน {args.sql} แล้ว ({n:,} บรรทัด · {size / 1024:.0f} KB)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    dbp, sqlp = Path(args.db), Path(args.sql)
    if dbp.exists() and not args.force:
        print(f"มี {dbp} อยู่แล้ว ไม่ทับให้ (ใส่ --force ถ้าต้องการทับ)")
        return 0
    if dbp.exists():
        dbp.unlink()
    if db.restore_sql(sqlp, dbp):
        conn = db.connect(dbp)
        print(f"กู้ฐานข้อมูลจาก {sqlp} แล้ว — "
              f"Steam {db.scan_count(conn)} รอบ · ตลาด {db.market_scan_count(conn)} รอบ")
    else:
        print(f"ไม่มี {sqlp} — เริ่มจากฐานข้อมูลเปล่า")
    return 0


def cmd_dash(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    if db.scan_count(conn) == 0:
        print("ยังไม่มีข้อมูล — รัน `game-radar scan` ก่อน", file=sys.stderr)
        return 1
    out = Path(args.out)
    meta = render.build(conn, out)
    print(f"สร้าง dashboard แล้ว: {out}")
    print(
        f"  {meta['total']} เกม | น่าซื้อ {meta['opportunities']} | "
        f"ยังไม่มีใครสต็อก {meta['unstocked']} | ยังไม่วางขาย {meta['upcoming']} | "
        f"ไอดีของคุณ {meta['mine']}"
    )
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    rows = db.latest_snapshot_per_title(conn)
    if not rows:
        print("ยังไม่มีข้อมูล — รัน `game-radar scan` ก่อน", file=sys.stderr)
        return 1

    stocked = db.latest_market(conn, "platform")
    mine = db.latest_market(conn, "mine")
    delta = db.market_delta(conn, "platform")

    items = []
    for row in rows:
        hist = [c for _, c in db.ccu_history(conn, row["appid"])]
        a = assess(conn, row, hist, stocked, mine, delta)
        if args.prospects_only and a.opportunity_score <= 0:
            continue
        items.append(a)
    items.sort(key=lambda a: -a.opportunity_score)

    fresh_th = {"upcoming": "ยังไม่ขาย", "fresh": "<1 ปี", "recent": "1-2 ปี",
                "old": ">2 ปี", "unknown": "?"}
    print(f"\n{'น่าซื้อ':>7} {'กระแส':>6} {'ราคา':>7} {'อายุ':<10} {'สต็อกตลาด':<12} เกม")
    print("-" * 84)
    for a in items[: args.limit]:
        price = f"{a.price_baht:,.0f}" if a.price_baht is not None else "-"
        if a.stocked_mine:
            stock = f"คุณ {a.stocked_mine}/{a.stocked_total}"
        elif a.stocked_total == 0:
            stock = "ยังไม่มีใคร"
        else:
            stock = f"คู่แข่ง {a.stocked_total}"
        co = " [co-op]" if a.is_coop else ""
        print(f"{a.opportunity_score:>7.1f} {a.surge_score:>6.1f} {price:>7} "
              f"{fresh_th.get(a.freshness, '?'):<10} {stock:<12} {a.name}{co}")
    return 0


# ---------- สต็อกไอดีของร้าน ----------
# ทุกคำสั่งในหมวดนี้เปิด stock.sqlite3 ไม่ใช่ radar.sqlite3

def _stock(args: argparse.Namespace):
    return stock.connect(Path(args.stock_db))


def _need_account(conn, label: str):
    a = stock.find_account(conn, label)
    if a is None:
        print(f"ไม่มีไอดีชื่อ {label} — ดูรายชื่อด้วย `game-radar stock list`",
              file=sys.stderr)
    return a


def cmd_stock_add(args: argparse.Namespace) -> int:
    conn = _stock(args)
    try:
        stock.add_account(
            conn, label=args.label, email=args.email, login=args.login,
            vault_ref=args.vault, guard_note=args.guard, note=args.note,
        )
    except Exception as e:  # UNIQUE ชนได้ทั้ง label และ email
        print(f"เพิ่มไม่ได้: {e}", file=sys.stderr)
        return 1
    print(f"เพิ่มไอดี {args.label} ({args.email}) แล้ว")
    if not args.vault:
        print("  เตือน: ยังไม่ได้ระบุ --vault ว่ารหัสผ่านอยู่รายการไหนใน password manager")
    return 0


def cmd_stock_buy(args: argparse.Namespace) -> int:
    conn = _stock(args)
    a = _need_account(conn, args.account)
    if a is None:
        return 1
    name = args.name or _radar_name(args, args.appid)
    try:
        stock.add_license(conn, a["id"], args.appid, name, args.cost, args.at, args.note)
    except Exception as e:
        print(f"บันทึกไม่ได้: {e}", file=sys.stderr)
        return 1
    price = f"{args.cost:,.0f} บาท" if args.cost is not None else "ไม่ระบุราคา"
    print(f"บันทึกแล้ว: {name or args.appid} เข้าไอดี {args.account} ({price})")
    return 0


def cmd_stock_rent(args: argparse.Namespace) -> int:
    conn = _stock(args)
    a = _need_account(conn, args.account)
    if a is None:
        return 1
    if a["status"] != "active":
        print(f"ไอดี {args.account} สถานะ {a['status']} — ปล่อยเช่าไม่ได้", file=sys.stderr)
        return 1
    busy = stock.busy_rental(conn, a["id"], args.start)
    if busy is not None and not args.force:
        print(f"ไอดี {args.account} ติดเช่าอยู่ถึง {busy['ends_on']} "
              f"({busy['renter'] or 'ไม่ระบุชื่อ'}) — ใส่ --force ถ้าจะจองซ้อนจริง ๆ",
              file=sys.stderr)
        return 1
    rid, end = stock.open_rental(
        conn, a["id"], args.days, appid=args.appid, renter=args.renter,
        contact=args.contact, price_baht=args.price, starts_on=args.start, note=args.note,
    )
    print(f"เปิดการเช่า #{rid} — ไอดี {args.account} ถึง {end} ({args.days} วัน)")
    return 0


def cmd_stock_return(args: argparse.Namespace) -> int:
    conn = _stock(args)
    rid = args.rental
    if rid is None:
        a = _need_account(conn, args.account)
        if a is None:
            return 1
        busy = stock.busy_rental(conn, a["id"])
        if busy is None:
            print(f"ไอดี {args.account} ไม่มีการเช่าค้างอยู่", file=sys.stderr)
            return 1
        rid = busy["id"]
    if not stock.close_rental(conn, rid, args.at):
        print(f"ปิดการเช่า #{rid} ไม่ได้ (ไม่มีอยู่ หรือปิดไปแล้ว)", file=sys.stderr)
        return 1
    print(f"ปิดการเช่า #{rid} แล้ว")
    return 0


def cmd_stock_list(args: argparse.Namespace) -> int:
    conn = _stock(args)
    items = stock.account_overview(conn)
    if not items:
        print("ยังไม่มีไอดีในระบบ — เพิ่มด้วย `game-radar stock add`")
        return 0

    print(f"\n{'ไอดี':<8} {'สถานะ':<14} {'ทุน':>8} {'รายได้':>8} {'ครั้ง':>5}  เกม")
    print("-" * 86)
    for it in items:
        a, busy = it["row"], it["busy"]
        if a["status"] != "active":
            state = a["status"]
        elif busy is not None:
            state = f"เช่าถึง {busy['ends_on'][5:]}"
        else:
            state = "ว่าง"
        games = ", ".join(g["game_name"] or str(g["appid"]) for g in it["games"]) or "-"
        print(f"{a['label']:<8} {state:<14} {it['cost']:>8,.0f} {it['revenue']:>8,.0f} "
              f"{it['rentals']:>5}  {games[:44]}")

    total_cost = sum(i["cost"] for i in items)
    total_rev = sum(i["revenue"] for i in items)
    free = sum(1 for i in items if i["busy"] is None and i["row"]["status"] == "active")
    print("-" * 86)
    print(f"ไอดีทั้งหมด {len(items)} · ว่าง {free} · ทุนรวม {total_cost:,.0f} "
          f"· รายได้รวม {total_rev:,.0f} บาท")

    late = stock.overdue_rentals(conn)
    if late:
        print(f"\nเลยกำหนดคืนแล้วยังไม่ได้ปิด {len(late)} รายการ:")
        for r in late:
            who = " ".join(x for x in (r["renter"] or "ไม่ระบุชื่อ", r["contact"]) if x)
            print(f"  #{r['id']} ไอดี {r['label']} ครบ {r['ends_on']} ({who})")
    return 0


def _radar_names(args: argparse.Namespace) -> dict[int, str]:
    """ชื่อเกมจากฐาน radar — ไม่มีก็ไม่เป็นไร stock ทำงานได้เองอยู่แล้ว"""
    p = Path(args.db)
    if not p.exists():
        return {}
    conn = db.connect(p)
    return {r["appid"]: r["name"] for r in conn.execute("SELECT appid, name FROM title")}


def _radar_name(args: argparse.Namespace, appid: int) -> str | None:
    return _radar_names(args).get(appid)


def cmd_stock_roi(args: argparse.Namespace) -> int:
    conn = _stock(args)
    games = stock.per_game(conn, args.window)
    if not games:
        print("ยังไม่มีเกมในสต็อก — บันทึกด้วย `game-radar stock buy`")
        return 0
    names = _radar_names(args)
    rows = sorted(games.values(), key=lambda g: -(g["revenue"] - g["cost"]))

    print(f"\nหน้าต่าง {args.window} วันล่าสุด")
    print(f"{'ไอดี':>4} {'ทุน':>8} {'รายได้':>8} {'กำไร':>9} {'คืนทุน':>7} "
          f"{'ปล่อยออก':>8}  เกม")
    print("-" * 82)
    for g in rows:
        roi = f"{g['roi'] * 100:.0f}%" if g["roi"] is not None else "-"
        util = f"{g['utilization'] * 100:.0f}%" if g["utilization"] is not None else "-"
        name = g["name"] or names.get(g["appid"]) or str(g["appid"])
        print(f"{g['copies']:>4} {g['cost']:>8,.0f} {g['revenue']:>8,.0f} "
              f"{g['revenue'] - g['cost']:>9,.0f} {roi:>7} {util:>8}  {name[:34]}")
    return 0


def cmd_stock_demand(args: argparse.Namespace) -> int:
    """เทียบดีมานด์จริงของร้าน กับคะแนนที่เรดาร์ให้ไว้

    นี่คือจุดที่สองฐานมาเจอกัน: radar เดาว่า "ควรซื้อเกมไหน" จาก *ซัพพลาย*
    ของคู่แข่ง ส่วนตารางนี้บอกว่า "ที่ซื้อไปแล้วปล่อยออกจริงไหม" ซึ่งเป็นดีมานด์
    ถ้าเกมคะแนนสูงแต่ปล่อยไม่ออกซ้ำ ๆ แปลว่าสูตรใน score.py ผิด ไม่ใช่ตลาดผิด
    """
    p = Path(args.db)
    if not p.exists():
        print(f"ไม่มีฐาน radar ที่ {p} — รัน `game-radar restore` ก่อน", file=sys.stderr)
        return 1
    sconn = _stock(args)
    games = stock.per_game(sconn, args.window)
    if not games:
        print("ยังไม่มีเกมในสต็อก — บันทึกด้วย `game-radar stock buy`")
        return 0

    conn = db.connect(p)
    stocked = db.latest_market(conn, "platform")
    mine = db.latest_market(conn, "mine")
    delta = db.market_delta(conn, "platform")
    scores: dict[int, Any] = {}
    for row in db.latest_snapshot_per_title(conn):
        if row["appid"] not in games:
            continue
        hist = [c for _, c in db.ccu_history(conn, row["appid"])]
        scores[row["appid"]] = assess(conn, row, hist, stocked, mine, delta)

    rows = sorted(games.values(), key=lambda g: -(g["utilization"] or 0))
    print(f"\nหน้าต่าง {args.window} วันล่าสุด · น่าซื้อ = คะแนนที่เรดาร์ให้ไว้")
    print(f"{'ปล่อยออก':>8} {'น่าซื้อ':>7} {'กระแส':>6} {'สต็อกตลาด':>10} {'ไอดีเรา':>7}  เกม")
    print("-" * 78)
    for g in rows:
        a = scores.get(g["appid"])
        util = f"{g['utilization'] * 100:.0f}%" if g["utilization"] is not None else "-"
        name = g["name"] or (a.name if a else None) or str(g["appid"])
        opp = f"{a.opportunity_score:.1f}" if a else "-"
        surge = f"{a.surge_score:.1f}" if a else "-"
        market = str(stocked.get(g["appid"], 0))
        print(f"{util:>8} {opp:>7} {surge:>6} {market:>10} {g['copies']:>7}  {name[:32]}")
    missing = [g for g in rows if g["appid"] not in scores]
    if missing:
        print(f"\n({len(missing)} เกมยังไม่มีในเรดาร์ — คะแนนแสดงเป็น -)")
    return 0


def cmd_stock_export(args: argparse.Namespace) -> int:
    conn = _stock(args)
    out = Path(args.dir)
    if (ROOT / "data") in out.resolve().parents or out.resolve() == ROOT / "data":
        print("อย่าส่งออกลง data/ — ไฟล์มีอีเมลและชื่อลูกค้า เลือกที่นอกโปรเจกต์",
              file=sys.stderr)
        return 1
    paths = stock.export_csv(conn, out)
    for p in paths:
        print(f"เขียน {p}")
    print("ไฟล์นี้มีอีเมลและชื่อลูกค้า — เก็บให้ดี อย่าอัปขึ้นที่สาธารณะ")
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    """ดึงสถานะไอดี + ยอด/ประวัติเช่าของร้านเราจากหลังบ้าน 499k

    ต้องมี SyncProfile Brave (พอร์ต 9222) รันอยู่และ login 499k ค้าง
    เขียน data/own.sqlite3 + สร้าง out/own.html — ไฟล์ local ทั้งคู่ ไม่ขึ้น git
    exit code: 0 = สำเร็จ · 2 = session หมดอายุ (ต้อง re-login) · 3 = ดึงไม่ได้
    """
    try:
        data = mine.seller_fetch()
    except mine.MineAuthExpired as e:
        print(f"MINE_AUTH_EXPIRED — {e}", file=sys.stderr)
        return 2
    except mine.MineUnavailable as e:
        print(f"MINE_UNAVAILABLE — {e}", file=sys.stderr)
        return 3

    conn = mine.connect(Path(args.own_db))
    try:
        n = mine.save_pull(conn, data)
        html = mine.render_html(conn)
    finally:
        conn.close()

    dash = data["dash"]
    print(f"ร้านเรา: ไอดี {n['accounts']} ใบ · รายการ {n['transactions']} รายการ")
    print(f"  ยอดทั้งหมด ฿{dash.get('amount_all'):.2f} · ค่าธรรมเนียม ฿{dash.get('fee_all'):.2f}"
          f" · รายได้ ฿{dash.get('income_all'):.2f}")
    print(f"  เดือนนี้ ฿{dash.get('amount_month'):.2f} (กำไร ฿{dash.get('income_month'):.2f})"
          f" · วันนี้ ฿{dash.get('income_today'):.2f} · กำลังเช่า ฿{dash.get('ongoing_profit'):.2f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"เขียนหน้า {out}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rc = cmd_scan(args)
    return rc or cmd_dash(args)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="game-radar", description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_scan_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--cc", default="th", help="ประเทศสำหรับราคา (ค่าเริ่มต้น th)")
        sp.add_argument("--metadata-limit", type=int, default=250)
        sp.add_argument("--review-limit", type=int, default=60,
                        help="ดึงรีวิวสูงสุดกี่เกมต่อรอบ (แคช 7 วัน)")

    sp = sub.add_parser("scan", help="เก็บข้อมูลหนึ่งรอบ")
    add_scan_args(sp)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("dump", help="เขียนฐานข้อมูลออกเป็นไฟล์ .sql (สำหรับเก็บใน git)")
    sp.add_argument("--sql", default=str(DEFAULT_SQL))
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("restore", help="สร้างฐานข้อมูลจากไฟล์ .sql")
    sp.add_argument("--sql", default=str(DEFAULT_SQL))
    sp.add_argument("--force", action="store_true", help="ทับฐานข้อมูลเดิมถ้ามีอยู่")
    sp.set_defaults(func=cmd_restore)

    sp = sub.add_parser("market", help="เก็บสต็อกของตลาดเช่าหนึ่งรอบ (เบา รันทุกวัน)")
    sp.add_argument("--allow-fail", action="store_true",
                    help="ถ้าดึงไม่ได้ให้เตือนแล้วไปต่อ แทนที่จะล้ม (ใช้บน CI)")
    sp.set_defaults(func=cmd_market)

    sp = sub.add_parser("dash", help="สร้างหน้า dashboard")
    sp.add_argument("--out", default=str(DEFAULT_OUT))
    sp.set_defaults(func=cmd_dash)

    sp = sub.add_parser("top", help="ดูอันดับในเทอร์มินัล")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sp.add_argument("--all", dest="prospects_only", action="store_false")
    sp.set_defaults(func=cmd_top, prospects_only=True)

    sp = sub.add_parser("stock", help="สต็อกไอดีของร้าน (ฐานข้อมูลแยก ไม่ขึ้น git)")
    sp.add_argument("--stock-db", default=str(DEFAULT_STOCK_DB))
    ssub = sp.add_subparsers(dest="stock_cmd", required=True)

    q = ssub.add_parser("add", help="เพิ่มไอดีใหม่")
    q.add_argument("label", help="ชื่อเรียกในร้าน เช่น A01")
    q.add_argument("email", help="อีเมลที่ผูกกับ Steam")
    q.add_argument("--login", help="ชื่อบัญชี Steam (ห้ามใส่รหัสผ่าน)")
    q.add_argument("--vault", help="ชื่อรายการใน password manager ที่เก็บรหัสจริง")
    q.add_argument("--guard", help="Steam Guard authenticator อยู่เครื่องไหน")
    q.add_argument("--note")
    q.set_defaults(func=cmd_stock_add)

    q = ssub.add_parser("buy", help="บันทึกเกมที่ซื้อเข้าไอดี")
    q.add_argument("account", help="ชื่อไอดี เช่น A01")
    q.add_argument("appid", type=int)
    q.add_argument("--cost", type=float, help="ราคาที่จ่ายจริง (บาท)")
    q.add_argument("--name", help="ชื่อเกม (ไม่ใส่จะดึงจากเรดาร์ให้)")
    q.add_argument("--at", help="วันที่ซื้อ YYYY-MM-DD (ค่าเริ่มต้นวันนี้)")
    q.add_argument("--note")
    q.set_defaults(func=cmd_stock_buy)

    q = ssub.add_parser("rent", help="เปิดการเช่า")
    q.add_argument("account")
    q.add_argument("days", type=int)
    q.add_argument("--appid", type=int, help="เช่าเพราะเกมไหน (สำคัญ — เป็นข้อมูลดีมานด์)")
    q.add_argument("--renter", help="ชื่อผู้เช่า")
    q.add_argument("--contact", help="ช่องทางติดต่อ")
    q.add_argument("--price", type=float, help="ค่าเช่าที่เก็บได้ (บาท)")
    q.add_argument("--start", help="วันเริ่ม YYYY-MM-DD (ค่าเริ่มต้นวันนี้)")
    q.add_argument("--force", action="store_true", help="จองซ้อนทั้งที่ไอดียังติดอยู่")
    q.add_argument("--note")
    q.set_defaults(func=cmd_stock_rent)

    q = ssub.add_parser("return", help="ปิดการเช่า")
    q.add_argument("account", nargs="?", help="ชื่อไอดี (ปิดตัวที่ค้างอยู่)")
    q.add_argument("--rental", type=int, help="ระบุเลขที่การเช่าตรง ๆ")
    q.add_argument("--at", help="วันที่คืน YYYY-MM-DD (ค่าเริ่มต้นวันนี้)")
    q.set_defaults(func=cmd_stock_return)

    q = ssub.add_parser("list", help="ดูไอดีทั้งหมด ว่าง/ติดเช่า และของที่เลยกำหนด")
    q.set_defaults(func=cmd_stock_list)

    q = ssub.add_parser("roi", help="รายเกม: ทุน รายได้ คืนทุนกี่เปอร์เซ็นต์")
    q.add_argument("--window", type=int, default=30, help="หน้าต่างกี่วันล่าสุด")
    q.set_defaults(func=cmd_stock_roi)

    q = ssub.add_parser("demand", help="เทียบดีมานด์จริงกับคะแนนที่เรดาร์ให้ไว้")
    q.add_argument("--window", type=int, default=30)
    q.set_defaults(func=cmd_stock_demand)

    q = ssub.add_parser("export", help="ส่งออกเป็น CSV (มีข้อมูลลูกค้า เก็บให้ดี)")
    q.add_argument("dir", help="โฟลเดอร์ปลายทาง — ต้องอยู่นอกโปรเจกต์")
    q.set_defaults(func=cmd_stock_export)

    sp = sub.add_parser("mine", help="ร้านเรา: ดึงสถานะไอดี+ยอดเช่าจากหลังบ้าน 499k (ฐานแยก ไม่ขึ้น git)")
    sp.add_argument("--own-db", default=str(DEFAULT_OWN_DB))
    sp.add_argument("--out", default=str(DEFAULT_OWN_HTML))
    sp.set_defaults(func=cmd_mine)

    sp = sub.add_parser("run", help="scan แล้วสร้าง dashboard ต่อเลย")
    add_scan_args(sp)
    sp.add_argument("--out", default=str(DEFAULT_OUT))
    sp.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
