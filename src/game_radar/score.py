"""การตีความ snapshot — v2 หลังแบ็คเทสกับตลาดจริง

สิ่งที่ v1 เข้าใจผิด และแก้แล้วในไฟล์นี้:

1. **เคยคิดว่า single-player คือข้อดี** ผิดสุดขั้ว — จากแค็ตตาล็อกร้านเช่าจริง
   98% ของไอดีที่สต็อกอยู่กับเกมที่มี Multi-player ส่วน single-player ล้วนได้ 1%
   เพราะดีมานด์มาจาก "กลุ่มเพื่อนอยากเล่นด้วยกัน" เกม co-op หนึ่งเกมสร้างการเช่า
   3-4 ครั้งพร้อมกัน เกมเล่นคนเดียวสร้างได้ครั้งเดียว

2. **เคยใช้ CCU/อันดับเป็นตัวชี้วัด** ซึ่งวัด "ฐานผู้เล่นใหญ่" ไม่ใช่ "ดีมานด์เช่า"
   เทียบอันดับที่ v1 ให้ กับจำนวนไอดีที่ตลาดสต็อกจริง ได้ Spearman = -0.07 คือไม่เกี่ยวกันเลย

3. **เคยไม่สนวันวางขาย** ทั้งที่ 8 ใน 12 เกมที่ตลาดสต็อกหนักสุดออกภายใน 18 เดือน
   เกมเก่าที่ไม่มีใครสต็อก ไม่ใช่ช่องว่าง แต่คือเกมที่คนอยากเล่นซื้อไปหมดแล้ว

4. **เคยตัดเกมที่ยังไม่วางขายทิ้ง** ทั้งที่มันคือของที่ยังไม่มีใครสต็อกได้เลย
   ตอนนี้กลายเป็นสถานะของตัวเอง ไม่ใช่ blocker
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median

# ช่วงราคา (หน่วยสตางค์) — ตัวเลขทั้งหมดมาจากแค็ตตาล็อกร้านเช่าจริง ไม่ได้ตั้งเอา
#   87% ของไอดีที่ตลาดสต็อกอยู่ในช่วง ฿100-600 จึงเป็นแกนกลาง
#   แต่ ฿99 (How to Fish) มี 15 ใบ = อันดับ 5 ของตลาด และ ฿856 (Subnautica 2) มี 11 ใบ
#   สองตัวนี้พิสูจน์ว่านอกช่วงยังขายได้ ต้องลาดลง ไม่ใช่ตัดหน้าผา
#   ของที่ไม่มีดีมานด์จริงคือ ฿23 และ ฿57 (2 กับ 1 ใบ) ซึ่งต่ำกว่ามาก
PRICE_CORE_MIN = 12_000    # ฿120
PRICE_CORE_MAX = 50_000    # ฿500
PRICE_FLOOR = 3_000        # ฿30 — ต่ำกว่านี้คนซื้อขาดเองถูกกว่าเช่า
PRICE_CEIL = 110_000       # ฿1,100 — สูงกว่านี้ร้านจมทุนนานเกิน
MIN_PRICE_FIT = 0.55

# ชื่อเดิมที่โค้ดอื่นยังอ้างถึง (ตัวกรองบน dashboard ใช้ช่วงนี้แสดงผล)
PRICE_SWEET_MIN = 10_000
PRICE_SWEET_MAX = 60_000


def price_fit(price: int | None) -> float:
    """ความเหมาะของราคาต่อการปล่อยเช่า — ลาดลงนอกแกนกลาง ไม่ใช่ตัดทันที

    เวอร์ชันแรกใช้ if ราคา < ฿100 แล้วหัก 40% ทันที ซึ่งทำให้ How to Fish
    ที่ ฿98.58 โดนหักเต็ม ๆ เพราะถูกกว่าเส้นอยู่ 1.42 บาท ทั้งที่มันคือ
    เกมที่ตลาดสต็อกมากเป็นอันดับ 5 — เส้นแบบนั้นวัดอะไรไม่ได้เลย
    """
    if price is None:
        return 1.0
    if PRICE_CORE_MIN <= price <= PRICE_CORE_MAX:
        return 1.0
    if price < PRICE_CORE_MIN:
        span = PRICE_CORE_MIN - PRICE_FLOOR
        t = (price - PRICE_FLOOR) / span if span else 1.0
    else:
        span = PRICE_CEIL - PRICE_CORE_MAX
        t = (PRICE_CEIL - price) / span if span else 0.0
    t = max(0.0, min(1.0, t))
    return round(MIN_PRICE_FIT + t * (1.0 - MIN_PRICE_FIT), 3)

MIN_DAYS_FOR_HISTORY = 3
CHART_SIZE = 100

# เกมที่ออกไม่เกินช่วงนี้คือกลุ่มที่ตลาดเช่ายังเคลื่อนไหว
FRESH_DAYS = 365
RECENT_DAYS = 730

# พื้นขั้นต่ำของจำนวนคนเล่น — วัดจากแค็ตตาล็อกร้านเช่าจริง 16 เกมที่จับคู่กับ CCU ได้
# ตัวที่ต่ำสุดที่ตลาดยอมสต็อกยังมี 3,795 คน ค่ากลางอยู่ที่ 21,670
# ไม่มีพื้นนี้ เกมเล็กที่โตจาก 16 เป็น 177 คนจะได้คะแนนโตสูงกว่าเกมจริงทุกตัว
MIN_CCU_FOR_RENTAL = 3_000

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_release(text: str | None) -> date | None:
    """แกะวันวางขายจากสตริงของ Steam

    รูปแบบที่เจอจริง: '20 Aug, 2026' · 'Aug 2026' · '2026' · 'Q4 2026' · 'Coming soon'
    อันไหนแกะไม่ได้คืน None แล้วให้ผู้เรียกตัดสินใจเอง ไม่เดามั่ว
    """
    if not text:
        return None
    t = text.strip().lower().replace(",", " ")
    mon = next((_MONTHS[k] for k in _MONTHS if k in t), None)
    year = re.search(r"(19|20)\d{2}", t)
    if not year:
        return None
    y = int(year.group(0))
    day = re.search(r"\b(\d{1,2})\b(?!\d)", t.replace(year.group(0), ""))
    try:
        return date(y, mon or 1, int(day.group(1)) if (day and mon) else 1)
    except ValueError:
        return None


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
    age_days: int | None
    freshness: str
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
    in_coop_topsellers: bool
    in_coop_upcoming: bool
    in_coop_new: bool
    coop_topsellers_rank: int | None
    coop_upcoming_rank: int | None
    coop_new_rank: int | None
    stocked_total: int
    stocked_mine: int
    stock_delta: int
    status: str
    opportunity_score: float
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    history: list[int] = field(default_factory=list)

    @property
    def price_baht(self) -> float | None:
        return None if self.price_final is None else self.price_final / 100


def _surge_from_history(ccu: int, hist: list[int]) -> tuple[float, float]:
    baseline = median(hist) if hist else ccu
    growth = ccu / baseline if baseline > 0 else 1.0
    return growth, growth * math.log10(max(ccu, 10))


def _surge_from_rank(
    ccu: int | None, rank: int | None, last_week: int | None
) -> tuple[float | None, float, str]:
    """ฐานสำรองตอนยังไม่มีประวัติของตัวเอง

    Steam ส่ง last_week_rank มาเสมอ และส่งค่าเกิน 100 ได้ (เจอ 152 มาแล้ว)
    ฐาน chart_entry จึงแทบไม่ได้ใช้ ส่วนการเข้าชาร์ตใหม่ดูจาก last_week > CHART_SIZE
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


def _freshness(age: int | None, coming_soon: bool) -> str:
    if coming_soon:
        return "upcoming"
    if age is None:
        return "unknown"
    if age <= FRESH_DAYS:
        return "fresh"
    if age <= RECENT_DAYS:
        return "recent"
    return "old"


def _opportunity(a: dict) -> float:
    """คะแนนโอกาสสำหรับร้านที่เพิ่งเข้าตลาด

    ตั้งใจให้ตอบคำถามเดียว: "ควรเอาเงินไปซื้อไอดีเกมไหนก่อน"
    ไม่ใช่ "เกมไหนดัง" — เกมดังที่คู่แข่งสต็อกไว้ 50 ใบแล้วมีค่าเป็นศูนย์สำหรับรายใหม่
    """
    if a["status"] == "blocked":
        return 0.0
    if not (a["is_coop"] or a["is_multi"]):
        return 0.0
    if a["freshness"] in ("old", "unknown"):
        return 0.0
    # เกมที่วางขายแล้วต้องมีคนเล่นถึงพื้นก่อน — เกมยังไม่ขายยกเว้นเพราะยังไม่มี CCU ให้วัด
    if a["status"] == "prospect" and (a["ccu"] or 0) < MIN_CCU_FOR_RENTAL:
        return 0.0

    # เกมยังไม่วางขายไม่มี CCU ไม่มีอันดับ ไม่มีประวัติ — สัญญาณเดียวที่เหลือคือ
    # ลำดับในหน้า "popular upcoming" ของ Steam ซึ่งเรียงตามยอด wishlist
    # ถ้าไม่ใช้ตรงนี้ เกมยังไม่ออกทุกตัวจะได้คะแนนเท่ากันหมดจนเรียงลำดับไม่ได้
    def from_rank(r: int | None, weight: float) -> float:
        return 0.0 if not r else weight / (1 + r / 15)

    if a["status"] == "upcoming":
        base = from_rank(a["coop_upcoming_rank"], 6.5)
    else:
        # เกมที่วางขายแล้ว: เอาสัญญาณที่แรงกว่าระหว่างกระแสของตัวเอง
        # กับการติดอันดับขายดีในหมวด co-op
        base = max(a["surge_score"], from_rank(a["coop_topsellers_rank"], 6.0))
    if base <= 0:
        return 0.0

    # ยิ่งคู่แข่งสต็อกเยอะ ยิ่งเข้าไปช้า — 0 ใบได้เต็ม, 50 ใบเหลือแทบไม่มี
    stocked = a["stocked_total"] - a["stocked_mine"]
    room = 1.0 / (1.0 + stocked / 8)

    fresh_boost = {"upcoming": 1.6, "fresh": 1.35, "recent": 1.0}[a["freshness"]]
    coop_boost = 1.25 if a["is_coop"] else 1.0

    return round(
        base * room * fresh_boost * coop_boost * price_fit(a["price_final"]), 2
    )


def assess(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    hist: list[int],
    stocked: dict[int, int] | None = None,
    mine: dict[int, int] | None = None,
    stock_delta: dict[int, int] | None = None,
) -> Assessment:
    stocked = stocked or {}
    mine = mine or {}
    stock_delta = stock_delta or {}

    ccu = row["ccu"]
    rank = row["played_rank"]
    last_week = row["last_week_rank"]

    prior = hist[:-1] if len(hist) > 1 else []
    if ccu and len(prior) >= MIN_DAYS_FOR_HISTORY:
        growth, score = _surge_from_history(ccu, prior)
        basis = "history"
    else:
        growth, score, basis = _surge_from_rank(ccu, rank, last_week)

    rel = parse_release(row["release_date"])
    age = (date.today() - rel).days if rel else None
    coming = bool(row["coming_soon"])
    fresh = _freshness(age, coming)

    blockers: list[str] = []
    notes: list[str] = []

    if row["is_free"]:
        blockers.append("เกมฟรี — ไม่มีอะไรให้เช่า")
    if (row["type"] or "game") != "game":
        blockers.append(f"ไม่ใช่เกม (type={row['type']})")
    if not coming and row["price_final"] is None and not row["is_free"]:
        blockers.append("ไม่มีราคาในภูมิภาคไทย")

    if blockers:
        status = "blocked"
    elif coming:
        status = "upcoming"
    else:
        status = "prospect"

    if not (row["is_coop"] or row["is_multi"]):
        notes.append("เล่นคนเดียวล้วน — ตลาดเช่าแทบไม่มีดีมานด์ (1% ของไอดีทั้งตลาด)")
    if fresh == "old":
        notes.append("ออกเกิน 2 ปี — คนที่อยากเล่นซื้อไปแล้ว")
    if row["is_online_pvp"]:
        notes.append("มี Online PvP — เสี่ยง anti-cheat แบนไอดีจาก IP กระโดด")

    n_all = stocked.get(row["appid"], 0)
    n_mine = mine.get(row["appid"], 0)
    if n_all == 0:
        notes.append("ยังไม่มีร้านไหนบนแพลตฟอร์มสต็อกเกมนี้")
    elif n_mine:
        share = n_mine / n_all * 100
        notes.append(f"คุณถือ {n_mine} จาก {n_all} ใบในตลาด ({share:.0f}%)")
    else:
        notes.append(f"คู่แข่งสต็อกไว้แล้ว {n_all} ใบ")

    d = stock_delta.get(row["appid"], 0)
    if d > 0:
        notes.append(f"คู่แข่งเพิ่งเพิ่มสต็อก +{d} ใบ")

    payload = {
        "status": status,
        "is_coop": bool(row["is_coop"]),
        "is_multi": bool(row["is_multi"]),
        "freshness": fresh,
        "surge_score": round(score, 2),
        "stocked_total": n_all,
        "stocked_mine": n_mine,
        "price_final": row["price_final"],
        "coop_upcoming_rank": row["coop_upcoming_rank"],
        "coop_topsellers_rank": row["coop_topsellers_rank"],
        "ccu": ccu,
    }

    return Assessment(
        appid=row["appid"],
        name=row["name"],
        header_image=row["header_image"],
        genres=json.loads(row["genres"] or "[]"),
        ccu=ccu,
        price_final=row["price_final"],
        price_currency=row["price_currency"],
        discount_percent=row["discount_percent"],
        release_date=row["release_date"],
        age_days=age,
        freshness=fresh,
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
        in_coop_topsellers=bool(row["in_coop_topsellers"]),
        in_coop_upcoming=bool(row["in_coop_upcoming"]),
        in_coop_new=bool(row["in_coop_new"]),
        coop_topsellers_rank=row["coop_topsellers_rank"],
        coop_upcoming_rank=row["coop_upcoming_rank"],
        coop_new_rank=row["coop_new_rank"],
        stocked_total=n_all,
        stocked_mine=n_mine,
        stock_delta=d,
        status=status,
        opportunity_score=_opportunity(payload),
        blockers=blockers,
        notes=notes,
        history=hist,
    )
