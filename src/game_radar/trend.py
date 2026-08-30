"""แนวโน้มรายวัน — เกมไหนกำลังตก เกมไหนกำลังมา

**คนละเรื่องกับ Surge** ใน `score.py` — Surge ตอบว่า "ตอนนี้โตผิดปกติไหม"
ส่วนไฟล์นี้ตอบว่า "เทียบกับตัวเองเมื่อวานแล้วขึ้นหรือลง" ตัวแรกใช้ตัดสินใจซื้อ
ตัวหลังใช้ตัดสินใจ *ไม่* ซื้อ (กันซื้อตอนกระแสพีคแล้วดีมานด์หายก่อนคืนทุน)
ยังไม่มีผลกับคะแนน เป็นข้อมูลประกอบก่อน

## ทำไมต้องจับคู่ชั่วโมง

CCU รวมของทั้งชาร์ตแกว่ง 5.2M–9.1M ใน 2 วัน = 1.7 เท่า จากเวลาของวันล้วน ๆ
เทียบ CCU ดิบข้ามรอบจึงเป็นการวัดนาฬิกา ไม่ใช่วัดเทรนด์

เคยลองหารด้วย CCU รวมของตลาดเพื่อตัดวัฏจักรออก **แล้วไม่พอ** — ช่วยแค่ 8 จาก
12 เกม เฉลี่ยลด noise ได้ 4 จุด และทำให้บางเกมแย่ลง (Project Zomboid 11.7% →
16.6%) เพราะแต่ละเกมมีโซนเวลาของตัวเอง เอาเกมฐานยุโรปไปหารด้วยตลาดที่เอเชีย
ครองก็เท่ากับยัดวัฏจักรที่ไม่ใช่ของมันเข้าไป

จึงเทียบเกมกับ **ตัวมันเองที่ชั่วโมงท้องถิ่นเดียวกัน** ซึ่งไม่ต้องสมมติว่า
ฐานผู้เล่นของมันเหมือนใคร
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# เวลาไทย — วัฏจักรผู้เล่นผูกกับนาฬิกาของคนเล่น ไม่ใช่ UTC
# ใช้ค่าคงที่ตายตัวได้เพราะไทยไม่มี DST
ICT = timezone(timedelta(hours=7))

# ยอมให้ห่างจากชั่วโมงเป้าหมายได้เท่านี้ยังนับว่า "ชั่วโมงเดียวกัน"
# ตั้ง 1.0 เพราะรอบเก็บจริงเลื่อนได้มาก — GitHub Actions หน่วง 43 นาที ถึง 3.5 ชม.
# แคบกว่านี้จะจับคู่ไม่ได้เลย กว้างกว่านี้วัฏจักรรายวันจะเริ่มเล็ดลอดเข้ามา
HOUR_TOLERANCE = 1.0

# ต้องมีอย่างน้อยกี่วันถึงจะยอมคิดให้
MIN_DAYS = 2


@dataclass
class Decay:
    """ผลเทียบชั่วโมงเดียวกันข้ามวันของเกมหนึ่ง"""
    pct: float                 # เปลี่ยนไปกี่ % จากวันแรกถึงวันล่าสุด
    days: int                  # ใช้กี่วัน — 2 วันเชื่อได้น้อยกว่า 4 วันมาก
    hour: float                # ชั่วโมงไทยที่ใช้เป็นจุดเทียบ
    points: list = field(default_factory=list)   # [(วันที่ ISO, ccu), ...]

    @property
    def per_day(self) -> float:
        """เปลี่ยนเฉลี่ยต่อวัน — เทียบข้ามเกมที่มีจำนวนวันไม่เท่ากันได้"""
        span = self.days - 1
        return self.pct / span if span > 0 else 0.0


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(ICT)


def decay_of(series: list[tuple[str, int]]) -> Decay | None:
    """หาชั่วโมงที่ครอบคลุมวันได้มากที่สุด แล้ววัดการเปลี่ยนแปลงที่ชั่วโมงนั้น

    ไม่เลือกชั่วโมงตายตัว (เช่นบังคับ 22:00) เพราะรอบเก็บเลื่อนไปมา
    เกมแต่ละตัวจึงอาจได้ชั่วโมงอ้างอิงต่างกัน ซึ่งไม่เป็นไร เพราะแต่ละเกม
    เทียบกับตัวเองอยู่แล้ว ไม่ได้เอาไปเทียบข้ามเกมที่ระดับ CCU ดิบ
    """
    pts = [(_local(t), c) for t, c in series if c]
    if len(pts) < MIN_DAYS:
        return None

    best: Decay | None = None
    best_key: tuple[int, float] = (0, 0.0)
    for anchor, _ in pts:
        target = anchor.hour + anchor.minute / 60
        # วันไหนมีจุดใกล้ target ที่สุด เอาจุดนั้นเป็นตัวแทนของวัน
        per_day: dict[object, tuple[float, int]] = {}
        for d, c in pts:
            gap = abs((d.hour + d.minute / 60) - target)
            if gap > HOUR_TOLERANCE:
                continue
            cur = per_day.get(d.date())
            if cur is None or gap < cur[0]:
                per_day[d.date()] = (gap, c)
        if len(per_day) < MIN_DAYS:
            continue
        days = sorted(per_day)
        first, last = per_day[days[0]][1], per_day[days[-1]][1]
        if not first:
            continue
        cand = Decay(
            pct=last / first - 1.0,
            days=len(days),
            hour=round(target, 2),
            points=[(d.isoformat(), per_day[d][1]) for d in days],
        )
        # เลือกชุดที่ครอบคลุมวันได้มากที่สุดก่อน เสมอกันค่อยเอาชุดที่จุดต่าง ๆ
        # เกาะชั่วโมงเป้าหมายแน่นกว่า (ผลรวมระยะห่างน้อยกว่า = วัฏจักรเล็ดลอดน้อยกว่า)
        gap_sum = sum(g for g, _ in per_day.values())
        key = (cand.days, -gap_sum)
        if best is None or key > best_key:
            best, best_key = cand, key
    return best


def decay_all(series_by_appid: dict[int, list[tuple[str, int]]]) -> dict[int, Decay]:
    out: dict[int, Decay] = {}
    for appid, series in series_by_appid.items():
        d = decay_of(series)
        if d is not None:
            out[appid] = d
    return out


def reviews_per_day(series: list[tuple[str, int]]) -> float | None:
    """รีวิวใหม่ต่อวัน — ตัวชี้ *นำ* เพราะคนซื้อวันนี้คือคนเล่นสัปดาห์หน้า

    คืน None จนกว่าจะมีอย่างน้อยสองจุดที่ห่างกันเกินครึ่งวัน
    (ตารางประวัติเพิ่งเริ่มเก็บ จะยังว่างอยู่หลายวัน — ไม่ใช่บั๊ก)
    """
    if len(series) < 2:
        return None
    (t0, n0), (t1, n1) = series[0], series[-1]
    span = (_local(t1) - _local(t0)).total_seconds() / 86400
    if span < 0.5 or n1 is None or n0 is None:
        return None
    return (n1 - n0) / span


def velocity_all(series_by_appid: dict[int, list[tuple[str, int]]]) -> dict[int, float]:
    out: dict[int, float] = {}
    for appid, series in series_by_appid.items():
        v = reviews_per_day(series)
        if v is not None:
            out[appid] = v
    return out
