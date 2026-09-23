"""tools/merge_radar_sql.py — รวมข้อมูล conflict ของ data/radar.sql ที่ระดับ SQLite (union)

ใช้เมื่อ git pull/merge แล้ว data/radar.sql ชนกัน (ทั้งสองฝั่งเป็น dump ของตารางเดียวกัน)
วิธี: โหลด stage :2 (ours = ฝั่งที่ rebase/merge เข้ามา) และ stage :3 (theirs = ฝั่งเรา) เป็น DB แยก
      → INSERT OR IGNORE (ไม่ยกคอลัมน์ id มาด้วย กัน id ชนกันคนละแถว) → ซ่อม sqlite_sequence
      → เขียน dump กลับเป็น data/radar.sql แล้ว git add ให้
รันจากโฟลเดอร์ repo:  python tools/merge_radar_sql.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
TABLES = ["title", "snapshot", "market_snapshot", "review_snapshot"]
AUTO_ID = {"snapshot", "market_snapshot", "review_snapshot"}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True)


def stage_bytes(stage: str) -> bytes | None:
    r = git("show", f":{stage}:data/radar.sql")
    return r.stdout if r.returncode == 0 and r.stdout else None


def table_cols(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]


def main() -> int:
    ours, theirs = stage_bytes("2"), stage_bytes("3")
    if ours is None or theirs is None:
        print("ไม่พบ conflict ของ data/radar.sql (ต้องมีทั้ง stage :2 และ :3)")
        return 1

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="radar_merge_"))
    try:
        (tmp / "ours.sql").write_bytes(ours)
        (tmp / "theirs.sql").write_bytes(theirs)

        for name in ("ours", "theirs"):
            p = tmp / f"{name}.db"
            if p.exists():
                p.unlink()
            con = sqlite3.connect(p)
            con.executescript((tmp / f"{name}.sql").read_text(encoding="utf-8"))
            con.commit()
            con.close()

        a = sqlite3.connect(tmp / "ours.db")
        before = {t: a.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in TABLES}
        a.execute("ATTACH DATABASE ? AS b", (str(tmp / "theirs.db"),))
        added: dict[str, int] = {}
        for t in TABLES:
            cols = [c for c in table_cols(a, t) if not (t in AUTO_ID and c == "id")]
            collist = ",".join(f'"{c}"' for c in cols)
            cur = a.execute(
                f'INSERT OR IGNORE INTO "{t}" ({collist}) SELECT {collist} FROM b."{t}"'
            )
            added[t] = cur.rowcount
        a.commit()

        # ซ่อม sqlite_sequence = max(rowid) จริง กัน id ถูกใช้ซ้ำแล้ว INSERT OR IGNORE กลืนแถวใหม่
        if a.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_sequence'").fetchone()[0]:
            a.execute("DELETE FROM sqlite_sequence")
            for t in sorted(AUTO_ID):
                mx = a.execute(f'SELECT MAX(rowid) FROM "{t}"').fetchone()[0] or 0
                a.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", (t, mx))
            a.commit()

        after = {t: a.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in TABLES}

        target = REPO / "data" / "radar.sql"
        with target.open("w", encoding="utf-8", newline="\n") as f:
            for line in a.iterdump():
                f.write(line + "\n")
        a.close()

        git("checkout", "--ours", "--", "docs/index.html")
        unmerged = git("diff", "--name-only", "--diff-filter=U").stdout.decode().split()
        git("add", "--", "data/radar.sql", "docs/index.html")
        print("ours (stage 2) :", before)
        print("บวกจากฝั่งเรา   :", added)
        print("รวมแล้ว        :", after)
        print("ไฟล์ที่ยัง unmerged:", unmerged or "(ไม่มี)")
        print("=> data/radar.sql รวมเสร็จ + git add ให้แล้ว")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if not (REPO / "data").exists():
        print("ห้ามรันนอก repo — ไม่พบ data/", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
