"""สร้างหน้า dashboard เป็นไฟล์ HTML ไฟล์เดียว

ตั้งใจให้เป็นไฟล์นิ่ง ๆ เปิดจากเครื่องได้เลย ไม่ต้องมี server
รูปปกดึงจาก CDN ของ Steam ตรง ๆ (ไฟล์อยู่บนเครื่องเรา ไม่ติด CSP)
ข้อมูลถูกฝังเป็น JSON แล้วให้ JS วาดการ์ด — ตัวกรองเลยทำงานทันทีไม่ต้องรีเฟรช
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import db
from .score import Assessment, assess

BASIS_LABEL = {
    "history": ["ประวัติจริง", "คำนวณจากข้อมูลที่เก็บเองย้อนหลัง แม่นสุด"],
    "weekly_rank": ["อันดับรายสัปดาห์", "เทียบอันดับกับสัปดาห์ก่อนที่ Steam ให้มา"],
    "chart_entry": ["เพิ่งเข้าชาร์ต", "ไม่มีอันดับสัปดาห์ก่อน = โผล่มาใหม่"],
    "none": ["ไม่มีฐานเทียบ", "ยังไม่ติดชาร์ต ประเมินกระแสไม่ได้"],
}

TEMPLATE = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Radar</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --fg:#14161a; --muted:#6b7280;
  --accent:#2563eb; --hot:#dc2626; --warm:#ea580c; --cool:#0891b2; --ok:#059669;
  --chip:#eef1f5;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]){
    --bg:#0d0f13; --panel:#161a21; --line:#252b35; --fg:#e6e9ee; --muted:#8b95a5;
    --accent:#60a5fa; --hot:#f87171; --warm:#fb923c; --cool:#22d3ee; --ok:#34d399;
    --chip:#1e242e;
  }
}
:root[data-theme=dark]{
  --bg:#0d0f13; --panel:#161a21; --line:#252b35; --fg:#e6e9ee; --muted:#8b95a5;
  --accent:#60a5fa; --hot:#f87171; --warm:#fb923c; --cool:#22d3ee; --ok:#34d399;
  --chip:#1e242e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:"Segoe UI",system-ui,-apple-system,"Noto Sans Thai",sans-serif;
  line-height:1.5}
.wrap{max-width:1240px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:1.6rem;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:.88rem;margin-bottom:22px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:10px 14px;min-width:110px}
.stat b{display:block;font-size:1.35rem;line-height:1.2}
.stat span{color:var(--muted);font-size:.75rem}
.bar{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;margin-bottom:22px;display:flex;flex-wrap:wrap;gap:16px;
  align-items:center}
.bar label{font-size:.82rem;display:flex;align-items:center;gap:6px;cursor:pointer}
.bar select,.bar input[type=search]{background:var(--bg);color:var(--fg);
  border:1px solid var(--line);border-radius:7px;padding:6px 9px;font-size:.82rem;
  font-family:inherit}
.grid{display:grid;gap:14px;
  grid-template-columns:repeat(auto-fill,minmax(310px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  overflow:hidden;display:flex;flex-direction:column}
.card.dim{opacity:.55}
.thumb{position:relative;aspect-ratio:460/215;background:var(--chip)}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.rankbadge{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.78);
  color:#fff;border-radius:6px;padding:3px 8px;font-size:.72rem;font-weight:600}
.pricebadge{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.78);
  color:#fff;border-radius:6px;padding:3px 8px;font-size:.75rem;font-weight:600}
.pricebadge .off{color:#a3e635}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:9px;flex:1}
.name{font-weight:650;font-size:.98rem;letter-spacing:-.01em}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{background:var(--chip);border-radius:5px;padding:2px 7px;font-size:.7rem;
  color:var(--muted);white-space:nowrap}
.chip.single{color:var(--ok)}
.chip.multi{color:var(--cool)}
.chip.pvp{color:var(--warm)}
.metrics{display:flex;gap:14px;align-items:flex-end;margin-top:auto}
.ccu b{font-size:1.15rem;display:block;line-height:1.15}
.ccu span{font-size:.7rem;color:var(--muted)}
.delta{font-size:.78rem;font-weight:600}
.up{color:var(--ok)} .down{color:var(--muted)} .new{color:var(--hot)}
.spark{margin-left:auto}
.surge{display:flex;align-items:center;gap:7px;font-size:.75rem;color:var(--muted);
  border-top:1px solid var(--line);padding-top:9px}
.score{font-weight:700;font-size:.95rem}
.s-hot{color:var(--hot)} .s-warm{color:var(--warm)} .s-mild{color:var(--muted)}
.basis{background:var(--chip);border-radius:5px;padding:2px 7px;font-size:.68rem}
.notes{font-size:.73rem;color:var(--muted);display:flex;flex-direction:column;gap:3px}
.blocked{color:var(--warm)}
.empty{text-align:center;color:var(--muted);padding:60px 20px}
.warn{background:var(--chip);border:1px solid var(--line);
  border-left:3px solid var(--warm);
  border-radius:8px;padding:12px 14px;margin-bottom:20px;font-size:.84rem}
</style>

<div class="wrap">
  <h1>Game Radar</h1>
  <div class="sub" id="sub"></div>
  <div id="warn"></div>
  <div class="stats" id="stats"></div>

  <div class="bar">
    <input type="search" id="q" placeholder="ค้นชื่อเกม..." style="min-width:180px">
    <label><input type="checkbox" id="fProspect" checked> เฉพาะเกมที่เช่าได้ (มีราคา)</label>
    <label>ผู้เล่น
      <select id="fMode">
        <option value="all">ทั้งหมด</option>
        <option value="single">Single-player ล้วน</option>
        <option value="multi">มี Multi-player</option>
        <option value="coop">มี Co-op</option>
      </select>
    </label>
    <label>แนว <select id="fGenre"><option value="">ทั้งหมด</option></select></label>
    <label>ราคา
      <select id="fPrice">
        <option value="all">ทั้งหมด</option>
        <option value="sweet">100-600 บาท (ช่วงเช่าคุ้ม)</option>
        <option value="cheap">ต่ำกว่า 100 บาท</option>
        <option value="rich">สูงกว่า 600 บาท</option>
      </select>
    </label>
    <label>เรียงตาม
      <select id="fSort">
        <option value="surge">คะแนนกระแส</option>
        <option value="ccu">คนเล่นตอนนี้</option>
        <option value="delta">อันดับพุ่ง</option>
        <option value="price">ราคาถูกสุด</option>
      </select>
    </label>
  </div>

  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" hidden>ไม่มีเกมที่ตรงเงื่อนไข</div>
</div>

<script>
const DATA = __DATA__;
const META = __META__;
const BASIS = __BASIS__;

const nf = new Intl.NumberFormat('th-TH');
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const baht = c => c == null ? '—' : '฿' + nf.format(Math.round(c / 100));

document.getElementById('sub').textContent =
  'สแกนล่าสุด ' + META.scanned_at + ' · ' + META.total + ' เกม · เก็บข้อมูลมาแล้ว ' +
  META.scans + ' รอบ';

document.getElementById('stats').innerHTML = [
  ['เกมทั้งหมด', META.total],
  ['เช่าได้', META.prospects],
  ['เพิ่งเข้าชาร์ต', META.new_entries],
  ['อันดับพุ่งขึ้น', META.climbers],
].map(([k, v]) => '<div class="stat"><b>' + nf.format(v) + '</b><span>' + k +
  '</span></div>').join('');

if (META.scans < 4) {
  document.getElementById('warn').innerHTML =
    '<div class="warn"><b>ยังเก็บข้อมูลไม่พอ</b> — เก็บมา ' + META.scans + ' รอบ ' +
    'คะแนนกระแสตอนนี้คำนวณจากอันดับรายสัปดาห์ที่ Steam ให้มา ซึ่งหยาบกว่าการเทียบ' +
    'ประวัติจริง พอรันครบ 4 รอบ (4 วัน) ระบบจะสลับไปใช้ฐาน "ประวัติจริง" เอง</div>';
}

const genres = [...new Set(DATA.flatMap(d => d.genres))].sort();
document.getElementById('fGenre').insertAdjacentHTML('beforeend',
  genres.map(g => '<option>' + esc(g) + '</option>').join(''));

function spark(hist) {
  if (!hist || hist.length < 2) return '';
  const w = 78, h = 26, mx = Math.max(...hist), mn = Math.min(...hist);
  const rng = (mx - mn) || 1;
  const pts = hist.map((v, i) =>
    (i / (hist.length - 1) * w).toFixed(1) + ',' +
    (h - (v - mn) / rng * h).toFixed(1)).join(' ');
  const col = hist[hist.length - 1] >= hist[0] ? 'var(--ok)' : 'var(--muted)';
  return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' +
    w + ' ' + h + '" role="img" aria-label="แนวโน้มผู้เล่น"><polyline points="' +
    pts + '" fill="none" stroke="' + col +
    '" stroke-width="1.8" stroke-linejoin="round"/></svg>';
}

function scoreClass(s) { return s >= 6 ? 's-hot' : s >= 3.5 ? 's-warm' : 's-mild'; }

function card(d) {
  const modes = [];
  if (d.is_single && !d.is_multi) modes.push('<span class="chip single">Single-player</span>');
  if (d.is_multi) modes.push('<span class="chip multi">Multi-player</span>');
  if (d.is_coop) modes.push('<span class="chip multi">Co-op</span>');
  if (d.is_online_pvp) modes.push('<span class="chip pvp">Online PvP</span>');
  if (d.has_family_sharing) modes.push('<span class="chip">Family Sharing</span>');

  let delta = '';
  if (d.entered_chart) delta = '<span class="delta new">เข้าชาร์ตใหม่ ▲' + d.rank_delta + '</span>';
  else if (d.rank_delta > 0) delta = '<span class="delta up">▲ ' + d.rank_delta + ' อันดับ</span>';
  else if (d.rank_delta < 0) delta = '<span class="delta down">▼ ' + (-d.rank_delta) + '</span>';

  const disc = d.discount_percent > 0
    ? '<span class="off">-' + d.discount_percent + '%</span> ' : '';
  const b = BASIS[d.surge_basis] || ['—', ''];

  const notes = d.blockers.map(x => '<div class="blocked">⚠ ' + esc(x) + '</div>')
    .concat(d.notes.slice(0, 2).map(n => '<div>· ' + esc(n) + '</div>')).join('');

  return '<article class="card' + (d.is_prospect ? '' : ' dim') + '">' +
    '<div class="thumb">' +
    (d.header_image ? '<img loading="lazy" src="' + esc(d.header_image) + '" alt="">' : '') +
    (d.played_rank ? '<span class="rankbadge">#' + d.played_rank + '</span>' : '') +
    '<span class="pricebadge">' + disc + (d.is_free ? 'ฟรี' : baht(d.price_final)) + '</span>' +
    '</div><div class="body">' +
    '<div class="name">' + esc(d.name) + '</div>' +
    '<div class="chips">' + modes.join('') + '</div>' +
    '<div class="chips">' + d.genres.map(g => '<span class="chip">' + esc(g) + '</span>').join('') + '</div>' +
    '<div class="metrics"><div class="ccu"><b>' +
    (d.ccu == null ? '—' : nf.format(d.ccu)) +
    '</b><span>คนเล่นตอนนี้</span></div>' + delta + spark(d.history) + '</div>' +
    '<div class="surge"><span class="score ' + scoreClass(d.surge_score) + '">' +
    d.surge_score.toFixed(1) + '</span><span>คะแนนกระแส</span>' +
    '<span class="basis" title="' + esc(b[1]) + '">' + esc(b[0]) + '</span></div>' +
    (notes ? '<div class="notes">' + notes + '</div>' : '') +
    '</div></article>';
}

function apply() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const onlyP = document.getElementById('fProspect').checked;
  const mode = document.getElementById('fMode').value;
  const genre = document.getElementById('fGenre').value;
  const price = document.getElementById('fPrice').value;
  const sort = document.getElementById('fSort').value;

  const rows = DATA.filter(d => {
    if (q && !d.name.toLowerCase().includes(q)) return false;
    if (onlyP && !d.is_prospect) return false;
    if (mode === 'single' && !(d.is_single && !d.is_multi)) return false;
    if (mode === 'multi' && !d.is_multi) return false;
    if (mode === 'coop' && !d.is_coop) return false;
    if (genre && !d.genres.includes(genre)) return false;
    const p = d.price_final;
    if (price === 'sweet' && !(p >= 10000 && p <= 60000)) return false;
    if (price === 'cheap' && !(p != null && p < 10000)) return false;
    if (price === 'rich' && !(p != null && p > 60000)) return false;
    return true;
  });

  const key = {
    surge: d => -d.surge_score,
    ccu: d => -(d.ccu == null ? -1 : d.ccu),
    delta: d => -(d.rank_delta == null ? -999 : d.rank_delta),
    price: d => d.price_final == null ? Infinity : d.price_final,
  }[sort];
  rows.sort((a, b) => key(a) - key(b));

  document.getElementById('grid').innerHTML = rows.map(card).join('');
  document.getElementById('empty').hidden = rows.length > 0;
}

['q', 'fProspect', 'fMode', 'fGenre', 'fPrice', 'fSort'].forEach(id =>
  document.getElementById(id).addEventListener('input', apply));
apply();
</script>
"""


def build(conn: sqlite3.Connection, out_path: Path) -> dict[str, int]:
    rows = db.latest_snapshot_per_title(conn)
    items: list[Assessment] = []
    for row in rows:
        hist = [c for _, c in db.ccu_history(conn, row["appid"])]
        items.append(assess(conn, row, hist))

    payload = []
    for row, a in zip(rows, items):
        d = asdict(a)
        d["is_free"] = bool(row["is_free"])
        d["history"] = a.history[-20:]
        payload.append(d)

    scanned_at = rows[0]["taken_at"] if rows else db.utcnow()
    try:
        scanned_at = (
            datetime.fromisoformat(scanned_at).astimezone().strftime("%d/%m/%Y %H:%M")
        )
    except ValueError:
        pass

    meta = {
        "scanned_at": scanned_at,
        "total": len(items),
        "prospects": sum(1 for a in items if a.is_prospect),
        "new_entries": sum(1 for a in items if a.entered_chart),
        "climbers": sum(1 for a in items if (a.rank_delta or 0) > 0),
        "scans": db.scan_count(conn),
    }

    html = (
        TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
        .replace("__META__", json.dumps(meta, ensure_ascii=False))
        .replace("__BASIS__", json.dumps(BASIS_LABEL, ensure_ascii=False))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return meta
