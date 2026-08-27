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

_UA = {"User-Agent": "game-radar/0.2 (own-shop inventory tracking)"}


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
        r = client.get(RENTAL_LIST, params=params)
        r.raise_for_status()
        data = r.json()
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
