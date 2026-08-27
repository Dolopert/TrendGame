"""หน้าตาคำสั่ง

  game-radar scan      เก็บข้อมูลหนึ่งรอบ (รันวันละครั้งพอ)
  game-radar dash      สร้างหน้า dashboard จากข้อมูลที่มี
  game-radar top       ดูอันดับในเทอร์มินัลเร็ว ๆ
  game-radar run       scan แล้ว dash ต่อเลย
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db, render, scan
from .score import assess

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "radar.sqlite3"
DEFAULT_OUT = ROOT / "out" / "dashboard.html"
DEFAULT_SQL = ROOT / "data" / "radar.sql"


def cmd_scan(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    result = scan.run_scan(conn, cc=args.cc, metadata_limit=args.metadata_limit)
    print(
        f"\nเก็บแล้ว {result['titles_seen']} เกม "
        f"(รายละเอียดใหม่ {result['metadata_fetched']} ตัว) "
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

    sp = sub.add_parser("run", help="scan แล้วสร้าง dashboard ต่อเลย")
    add_scan_args(sp)
    sp.add_argument("--out", default=str(DEFAULT_OUT))
    sp.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
