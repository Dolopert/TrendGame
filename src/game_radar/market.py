"""ฝั่งตลาดจริง — ดึงว่าร้านเช่าบนแพลตฟอร์มสต็อกเกมอะไรไว้กี่ไอดี

ทำไมต้องมี: สัญญาณจาก Steam บอกได้แค่ว่าเกมกำลังมา แต่บอกไม่ได้ว่า
"ตลาดเช่ารู้แล้วหรือยัง" ซึ่งเป็นตัวชี้ขาดของร้านที่เพิ่งเข้าตลาด —
เกมที่กำลังมา *และ* ยังไม่มีใครสต็อก คือของที่มีค่า ส่วนเกมที่คู่แข่ง
สต็อกไว้ 50 ไอดีแล้ว คือสนามที่เข้าไปช้าเกินไป

endpoint ที่ใช้เป็นของสาธารณะ เปิดอ่านได้จากหน้าร้านโดยไม่ต้องล็อกอิน
ยิงวันละครั้งพอ — อย่ายิงถี่กว่านี้ ไม่มีเหตุผลและเป็นการรบกวนเขาเปล่า ๆ
"""
from __future__ import annotations

from typing import Any

import httpx

RENTAL_LIST = (
    "https://store.499k-network.com/api/product/steam/rental/getGameList"
)

# ร้านของเราเองบนแพลตฟอร์มเดียวกัน (Online101Gaming)
OWN_SELLER_ID = 23566

# ใช้ UA แบบเบราว์เซอร์ทั่วไปแล้วต่อท้ายด้วยชื่อเครื่องมือ
# หน้าร้านอยู่หลัง Cloudflare ซึ่งเข้มกับ IP ของ datacenter (เช่นเครื่องของ GitHub)
# มากกว่า IP บ้าน UA ที่ไม่เหมือนเบราว์เซอร์เลยมักโดนปัดตกตั้งแต่ต้น
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 game-radar/0.2"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Referer": "https://store.499k-network.com/steam/rental",
}


class MarketUnavailable(RuntimeError):
    """ดึงข้อมูลตลาดไม่ได้ — แยกจากข้อผิดพลาดอื่นเพื่อให้ผู้เรียกเลือกได้ว่าจะล้มหรือข้าม"""


def _client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers=_UA, follow_redirects=True)


def _fetch_all(client: httpx.Client, owner: int | None = None) -> list[dict[str, Any]]:
    """ไล่ทุกหน้าจนครบ — แพลตฟอร์มแบ่งหน้าละ 12 เกม"""
    games: list[dict[str, Any]] = []
    page = 1
    while True:
        params: dict[str, Any] = {"page": page}
        if owner is not None:
            params["owner"] = owner
        try:
            r = client.get(RENTAL_LIST, params=params)
        except httpx.HTTPError as e:
            raise MarketUnavailable(f"ต่อไม่ติด: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise MarketUnavailable(
                f"HTTP {r.status_code} จาก {r.url} "
                f"(ตอบมา {len(r.text)} ตัวอักษร ขึ้นต้นว่า {r.text[:120]!r})"
            )
        try:
            data = r.json()
        except ValueError:
            raise MarketUnavailable(
                f"ตอบกลับมาไม่ใช่ JSON ขึ้นต้นว่า {r.text[:160]!r}"
            ) from None
        if not data.get("status"):
            break
        games.extend(data.get("games", []))
        total = data.get("totalPages", 1)
        if page >= total:
            break
        page += 1
    return games


def rental_market(client: httpx.Client) -> list[dict[str, Any]]:
    """สต็อกรวมของทุกร้านบนแพลตฟอร์ม"""
    return _fetch_all(client)


def rental_own(client: httpx.Client, seller_id: int = OWN_SELLER_ID) -> list[dict[str, Any]]:
    """สต็อกของร้านเราเอง"""
    return _fetch_all(client, owner=seller_id)
