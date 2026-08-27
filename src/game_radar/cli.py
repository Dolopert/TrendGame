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


def cmd_scan(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    result = scan.run_scan(conn, cc=args.cc, metadata_limit=args.metadata_limit)
    print(
        f"\nเก็บแล้ว {result['titles_seen']} เกม "
        f"(รายละเอียดใหม่ {result['metadata_fetched']} ตัว) "
        f"— รวมเก็บมาทั้งหมด {result['total_scans']} รอบ"
    )
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
        f"  {meta['total']} เกม | เช่าได้ {meta['prospects']} | "
        f"เพิ่งเข้าชาร์ต {meta['new_entries']} | อันดับพุ่ง {meta['climbers']}"
    )
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    conn = db.connect(Path(args.db))
    rows = db.latest_snapshot_per_title(conn)
    if not rows:
        print("ยังไม่มีข้อมูล — รัน `game-radar scan` ก่อน", file=sys.stderr)
        return 1

    items = []
    for row in rows:
        hist = [c for _, c in db.ccu_history(conn, row["appid"])]
        a = assess(conn, row, hist)
        if args.prospects_only and not a.is_prospect:
            continue
        items.append(a)
    items.sort(key=lambda a: -a.surge_score)

    print(f"\n{'คะแนน':>6}  {'CCU':>9}  {'ราคา':>9}  โหมด        เกม")
    print("-" * 78)
    for a in items[: args.limit]:
        mode = "Single" if a.is_single and not a.is_multi else "Multi" if a.is_multi else "-"
        price = f"{a.price_baht:,.0f}" if a.price_baht is not None else "-"
        ccu = f"{a.ccu:,}" if a.ccu is not None else "-"
        flag = " *ใหม่" if a.played_rank and not a.last_week_rank else ""
        print(f"{a.surge_score:>6.1f}  {ccu:>9}  {price:>9}  {mode:<10}  {a.name}{flag}")
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
