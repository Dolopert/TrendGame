"""การตีความ snapshot เป็น Surge และ Prospect

หลักการที่ยึด: **Surge กับ Prospect แยกกันเด็ดขาด**
  Surge    = เกมนี้กำลังพุ่งไหม        (เรื่องกระแส ไม่สนธุรกิจ)
  Prospect = เกมนี้เอาไปเช่าได้ไหม      (เรื่องธุรกิจ ไม่สนกระแส)
สิ่งที่อยากได้จริงคือจุดตัด — แต่ต้องคำนวณแยกกัน ไม่งั้นพอผลลัพธ์ห่วย
จะแยกไม่ออกว่าจับกระแสพลาด หรือกรองธุรกิจผิด

ทุกคะแนน Surge ติด `basis` มาด้วยเสมอ ว่าคำนวณจากฐานอะไร
เพราะวันแรก ๆ ที่ยังไม่มีข้อมูลย้อนหลัง คะแนนมันหยาบกว่ามาก
และ dashboard ต้องบอกความจริงข้อนี้ ไม่ใช่แสร้งว่าแม่นเท่ากัน
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from statistics import median

# ช่วงราคาที่ "เช่าคุ้ม" — ถูกกว่านี้คนซื้อขาดเอง แพงกว่านี้ร้านจมทุน
# หน่วยเป็นสตางค์ (Steam ส่งราคามาแบบคูณ 100 แล้ว)
PRICE_SWEET_MIN = 10_000   # ฿100
PRICE_SWEET_MAX = 60_000   # ฿600

MIN_DAYS_FOR_HISTORY = 3

# ชาร์ตของ Steam มี 100 อันดับ — อันดับสัปดาห์ก่อนที่เกินค่านี้แปลว่าตอนนั้นยังไม่ติดชาร์ต
CHART_SIZE = 100


@dataclass
class Assessment:
    appid: int
    name: str
    header_image: str | None
    genres: list[str]
    ccu: int | None
    price_final: int | None
    price_currency: str | None
    discount_percent: int | None
    release_date: str | None
    is_single: bool
    is_multi: bool
    is_coop: bool
    is_online_pvp: bool
    has_family_sharing: bool
    played_rank: int | None
    last_week_rank: int | None
    rank_delta: int | None
    entered_chart: bool
    growth_x: float | None
    surge_score: float
    surge_basis: str
    is_prospect: bool
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    history: list[int] = field(default_factory=list)

    @property
    def price_baht(self) -> float | None:
        return None if self.price_final is None else self.price_final / 100


def _surge_from_history(ccu: int, hist: list[int]) -> tuple[float, float]:
    """โตกี่เท่าเทียบค่ากลางของตัวเอง แล้วถ่วงด้วยขนาด

    log10 มีไว้กันเกมที่โตจาก 5 คนเป็น 100 คน (โต 20 เท่าแต่ไม่มีค่าเชิงธุรกิจ)
    """
    baseline = median(hist) if hist else ccu
    growth = ccu / baseline if baseline > 0 else 1.0
    return growth, growth * math.log10(max(ccu, 10))


def _surge_from_rank(
    ccu: int | None, rank: int | None, last_week: int | None
) -> tuple[float | None, float, str]:
    """ฐานสำรองสำหรับวันแรก ๆ ที่ยังไม่มีประวัติ

    ใช้ last_week_rank ที่ Steam แถมมากับชาร์ต

    ข้อควรรู้จากการยิงจริง: Steam ให้อันดับสัปดาห์ก่อนมาเสมอ แม้ตอนนั้นเกมจะอยู่
    นอก 100 อันดับ (เห็นค่าอย่าง 152 มาแล้ว) ฐาน chart_entry จึงแทบไม่ได้ใช้
    ส่วนการ "เพิ่งเข้าชาร์ต" ดูจาก last_week > CHART_SIZE แทน แล้วปล่อยให้
    สูตร delta คิดคะแนนให้เอง เพราะมันสะท้อนขนาดการกระโดดได้ละเอียดกว่าค่าคงที่
    """
    size = math.log10(max(ccu or 10, 10))
    if rank is None:
        return None, 0.0, "none"
    if not last_week:
        return None, 3.0 * size, "chart_entry"
    delta = last_week - rank
    if delta <= 0:
        return None, max(0.0, 1.0 + delta / 50) * size, "weekly_rank"
    return None, (1.0 + delta / 25) * size, "weekly_rank"


def assess(conn: sqlite3.Connection, row: sqlite3.Row, hist: list[int]) -> Assessment:
    ccu = row["ccu"]
    rank = row["played_rank"]
    last_week = row["last_week_rank"]

    prior = hist[:-1] if len(hist) > 1 else []
    if ccu and len(prior) >= MIN_DAYS_FOR_HISTORY:
        growth, score = _surge_from_history(ccu, prior)
        basis = "history"
    else:
        growth, score, basis = _surge_from_rank(ccu, rank, last_week)

    blockers: list[str] = []
    notes: list[str] = []

    if row["is_free"]:
        blockers.append("เกมฟรี — ไม่มีอะไรให้เช่า")
    if (row["type"] or "game") != "game":
        blockers.append(f"ไม่ใช่เกม (type={row['type']})")
    if row["coming_soon"]:
        blockers.append("ยังไม่วางขาย")
    if row["price_final"] is None and not row["is_free"]:
        blockers.append("ไม่มีราคาในภูมิภาคไทย")

    price = row["price_final"]
    if price is not None:
        if price < PRICE_SWEET_MIN:
            notes.append("ราคาถูกมาก คนน่าจะซื้อขาดเองมากกว่าเช่า")
        elif price > PRICE_SWEET_MAX:
            notes.append("ราคาสูง ต้องปล่อยเช่าหลายรอบกว่าจะคืนทุน")
    if row["is_online_pvp"]:
        notes.append("มี Online PvP — เสี่ยง anti-cheat แบนไอดีจาก IP กระโดด")
    if row["has_family_sharing"]:
        notes.append("รองรับ Family Sharing")
    if row["is_single"] and not row["is_multi"]:
        notes.append("Single-player ล้วน — ใช้ Offline Mode ปล่อยพร้อมกันได้ง่าย")

    return Assessment(
        appid=row["appid"],
        name=row["name"],
        header_image=row["header_image"],
        genres=json.loads(row["genres"] or "[]"),
        ccu=ccu,
        price_final=price,
        price_currency=row["price_currency"],
        discount_percent=row["discount_percent"],
        release_date=row["release_date"],
        is_single=bool(row["is_single"]),
        is_multi=bool(row["is_multi"]),
        is_coop=bool(row["is_coop"]),
        is_online_pvp=bool(row["is_online_pvp"]),
        has_family_sharing=bool(row["has_family_sharing"]),
        played_rank=rank,
        last_week_rank=last_week,
        rank_delta=(last_week - rank) if (rank and last_week) else None,
        entered_chart=bool(
            rank and rank <= CHART_SIZE and last_week and last_week > CHART_SIZE
        ),
        growth_x=growth,
        surge_score=round(score, 2),
        surge_basis=basis,
        is_prospect=not blockers,
        blockers=blockers,
        notes=notes,
        history=hist,
    )
