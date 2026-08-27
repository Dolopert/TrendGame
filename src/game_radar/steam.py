"""ตัวห่อ Steam API ทั้งหมด — ทุก endpoint ที่ใช้เป็นของฟรี ไม่ต้องใช้ API key

ยืนยันด้วยการยิงจริงแล้วทั้ง 4 ตัว (2026-08-27)
"""
from __future__ import annotations

import time
from typing import Any

import httpx

CHARTS = "https://api.steampowered.com/ISteamChartsService"
STORE = "https://store.steampowered.com/api"
USERSTATS = "https://api.steampowered.com/ISteamUserStats"

# หมวดหมู่ของ Steam ที่เราสนใจ (เลข id จาก appdetails.categories)
CAT_MULTI = 1
CAT_SINGLE = 2
CAT_COOP = 9
CAT_ONLINE_PVP = 36
CAT_ONLINE_COOP = 38
CAT_FAMILY_SHARING = 62

_UA = {"User-Agent": "game-radar/0.1 (personal research)"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers=_UA, follow_redirects=True)


def most_played(client: httpx.Client) -> list[dict[str, Any]]:
    """100 เกมที่คนเล่นเยอะสุดรายสัปดาห์ — มี last_week_rank ติดมาด้วย

    นี่คือตัวที่แก้ปัญหา cold start: มีข้อมูลเทียบสัปดาห์ก่อนตั้งแต่วันแรกที่รัน
    """
    r = client.get(f"{CHARTS}/GetMostPlayedGames/v1/")
    r.raise_for_status()
    return r.json().get("response", {}).get("ranks", [])


def by_concurrent(client: httpx.Client) -> list[dict[str, Any]]:
    """100 เกมเรียงตามคนเล่นพร้อมกัน ณ ตอนนี้ — ได้ CCU สด 100 ตัวใน request เดียว"""
    r = client.get(f"{CHARTS}/GetGamesByConcurrentPlayers/v1/")
    r.raise_for_status()
    return r.json().get("response", {}).get("ranks", [])


def featured(client: httpx.Client, cc: str = "th") -> dict[str, list[dict[str, Any]]]:
    """หน้าร้าน Steam: specials / new_releases / top_sellers / coming_soon

    บัคเก็ตละ ~10 ตัว แต่สำคัญเพราะเกมไวรัลใหม่ ๆ โผล่ที่นี่ก่อนติดชาร์ต CCU
    (ยืนยันแล้ว: How to Fish อยู่ใน specials)
    """
    r = client.get(f"{STORE}/featuredcategories", params={"cc": cc, "l": "en"})
    r.raise_for_status()
    data = r.json()
    out: dict[str, list[dict[str, Any]]] = {}
    for bucket in ("specials", "new_releases", "top_sellers", "coming_soon"):
        node = data.get(bucket)
        if isinstance(node, dict):
            out[bucket] = [i for i in node.get("items", []) if i.get("id")]
    return out


def current_players(client: httpx.Client, appid: int) -> int | None:
    """CCU ของเกมเดียว — ใช้เฉพาะเกมที่ไม่ติด top-100 (ไม่งั้นใช้ by_concurrent คุ้มกว่า)"""
    try:
        r = client.get(
            f"{USERSTATS}/GetNumberOfCurrentPlayers/v1/", params={"appid": appid}
        )
        r.raise_for_status()
        resp = r.json().get("response", {})
        return resp.get("player_count") if resp.get("result") == 1 else None
    except (httpx.HTTPError, ValueError):
        return None


def app_details(
    client: httpx.Client, appid: int, cc: str = "th"
) -> dict[str, Any] | None:
    """ข้อมูลเกม: ชื่อ ราคา หมวดหมู่ แนว ปก วันวางขาย

    endpoint นี้ถูก rate limit (~200 ครั้ง / 5 นาที) — ผู้เรียกต้องแคชผลไว้เอง
    """
    try:
        r = client.get(
            f"{STORE}/appdetails", params={"appids": appid, "cc": cc, "l": "en"}
        )
        if r.status_code == 429:
            time.sleep(20)
            r = client.get(
                f"{STORE}/appdetails", params={"appids": appid, "cc": cc, "l": "en"}
            )
        r.raise_for_status()
        node = r.json().get(str(appid))
        if not node or not node.get("success"):
            return None
        return node.get("data")
    except (httpx.HTTPError, ValueError):
        return None
