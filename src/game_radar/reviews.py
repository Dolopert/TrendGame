"""รีวิวจาก Steam — ใช้ตอบว่า "เกมนี้ควรปล่อยเช่ากี่วัน"

endpoint นี้เป็นของสาธารณะ ไม่ต้องใช้ key และ **หนึ่ง request ได้ทั้งสองอย่าง**:
  query_summary  ยอดรีวิวรวม บวก/ลบ และคำบรรยายคะแนน
  reviews[]      รีวิวรายอัน ซึ่งมี playtime_at_review = คนนั้นเล่นไปกี่นาทีตอนเขียน

ค่ากลางของ playtime คือของที่โปรเจกต์นี้อยากได้มาตั้งแต่ต้นแต่ไม่เคยมี —
แพลตฟอร์มขายเป็นแพ็ก 1/3/7 วัน ชั่วโมงเล่นจึงแปลตรงเป็นแพ็กที่ควรตั้ง
วัดจริงแล้วแยกกลุ่มได้ชัด: How to Fish 6 ชม. · R.E.P.O. 31 · Terraria 99

**ค่าเหล่านี้ยังไม่มีผลกับคะแนนน่าซื้อ** ตั้งใจให้เป็นข้อมูลประกอบก่อน
เพราะยังไม่รู้ว่าเกมยาวเช่าออกดีกว่าหรือแย่กว่าเกมสั้น (Terraria 99 ชม. ตลาดสต็อก
24 ใบ ส่วน How to Fish 6 ชม. สต็อก 15 ใบ — ยาวไม่ได้แปลว่าแย่)
รอข้อมูลตลาดสะสมพอแล้วค่อยตัดสินด้วยตัวเลข ไม่ใช่เดา
"""
from __future__ import annotations

from statistics import median
from typing import Any

import httpx

REVIEWS = "https://store.steampowered.com/appreviews/{appid}"

_UA = {"User-Agent": "game-radar/0.3"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers=_UA, follow_redirects=True)


def fetch(client: httpx.Client, appid: int, sample: int = 100) -> dict[str, Any] | None:
    """ดึงสรุปรีวิว + ค่ากลางชั่วโมงเล่น ด้วย request เดียว

    ใช้ filter=recent เพราะอยากรู้พฤติกรรมของคนที่เล่นอยู่ตอนนี้
    ไม่ใช่ค่าเฉลี่ยตลอดอายุเกมซึ่งถูกถ่วงด้วยคนยุคแรก
    """
    params = {
        "json": 1,
        "num_per_page": sample,
        "filter": "recent",
        "language": "all",
        "purchase_type": "all",
    }
    try:
        r = client.get(REVIEWS.format(appid=appid), params=params)
        r.raise_for_status()
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not d.get("success"):
        return None

    q = d.get("query_summary") or {}
    total = q.get("total_reviews") or 0
    pos = q.get("total_positive") or 0

    hours = [
        rev["author"]["playtime_at_review"] / 60
        for rev in d.get("reviews", [])
        if (rev.get("author") or {}).get("playtime_at_review")
    ]

    return {
        "review_total": total,
        "review_positive": pos,
        "review_ratio": round(pos / total, 4) if total else None,
        "review_desc": q.get("review_score_desc"),
        "playtime_median_h": round(median(hours), 1) if hours else None,
        "playtime_sample": len(hours),
    }
