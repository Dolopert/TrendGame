"""สร้างหน้า dashboard เป็นไฟล์ HTML ไฟล์เดียว

ตั้งใจให้เป็นไฟล์นิ่ง ๆ เปิดจากเครื่องได้เลย ไม่ต้องมี server
รูปปกดึงจาก CDN ของ Steam ตรง ๆ (ไฟล์อยู่บนเครื่องเรา ไม่ติด CSP)
ข้อมูลถูกฝังเป็น JSON แล้วให้ JS วาดการ์ด — ตัวกรองเลยทำงานทันทีไม่ต้องรีเฟรช
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
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
  /* พาเลตต์เดียวกับ Hotel Finance — โทนมืดอย่างเดียว ไม่มีโหมดสว่าง
     ตัดสีลงเหลือสองตัว: เขียว = ดี/เลือกอยู่ · ส้ม = ร้อน/ต้องระวัง
     ที่เหลือเป็นเทาสามระดับ (fg / muted / dim) ตามลำดับความสำคัญ */
  /* color-scheme ไม่ได้จัดสไตล์อะไรเลย แต่บอกเบราว์เซอร์ว่าให้วาด native widget
     ทุกตัว (popup ของ select, scrollbar, caret) ด้วยชุดสีมืด
     เป็นตัวเดียวที่แก้ "popup ขาวบนหน้ามืด" ได้จริง — CSS บน <option> ไม่มีผล
     จำเป็นเพราะถ้า JS ยังไม่ทันรันหรือพัง select จะกลับไปเป็นของ OS ทันที */
  color-scheme:dark;
  --bg:#151619; --panel:#191a1d; --chip:#202225; --line:#2b2d31;
  --fg:#ecedf0; --muted:#9a9ea7; --dim:#696d76;
  --accent:#4ade80; --ok:#4ade80; --warm:#ff8a4c; --hot:#ff8a4c; --cool:#9a9ea7;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",
    Arial,"Noto Sans Thai",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--font);
  line-height:1.5;min-height:100vh;background-attachment:fixed;
  background-image:radial-gradient(60% 50% at 80% -10%,#1d2733 0,transparent 60%),
                   radial-gradient(50% 40% at 0% 0%,#231a24 0,transparent 55%)}
.wrap{max-width:1240px;margin:0 auto;padding:48px 22px 60px}
.eyebrow{font-size:11px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--accent);font-weight:700}
h1{font-size:34px;font-weight:800;margin:8px 0 8px;letter-spacing:-.025em;
  line-height:1.08}
.sub{color:var(--muted);font-size:14px;margin-bottom:28px;max-width:640px}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:11px 16px;min-width:112px}
.stat b{display:block;font-size:19px;font-weight:750;line-height:1.25;
  font-family:var(--mono);letter-spacing:-.02em}
.stat span{color:var(--dim);font-size:10px;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase}
.bar{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:14px 16px;margin-bottom:22px;display:flex;flex-wrap:wrap;gap:16px;
  align-items:center}
.bar label,.bar .fld{font-size:.82rem;display:flex;align-items:center;gap:6px;
  cursor:pointer}
.bar .fld{color:var(--muted)}
.bar input[type=search]{background:var(--bg);color:var(--fg);
  border:1px solid var(--line);border-radius:10px;padding:7px 11px;font-size:.82rem;
  font-family:inherit;outline:none;transition:border-color .12s}
.bar input[type=search]:hover{border-color:var(--border-strong,var(--muted))}
.bar input[type=search]:focus{border-color:var(--accent)}
.bar input[type=search]::placeholder{color:var(--muted)}
.bar select{
  -webkit-appearance:none;-moz-appearance:none;appearance:none;
  background-color:var(--bg);color:var(--fg);
  border:1px solid var(--line);border-radius:10px;
  padding:7px 30px 7px 11px;font-size:.82rem;font-family:inherit;
  cursor:pointer;outline:none;transition:border-color .12s;
  background-image:
    linear-gradient(45deg,transparent 50%,currentColor 50%),
    linear-gradient(135deg,currentColor 50%,transparent 50%);
  background-position:calc(100% - 15px) calc(50% + 1px),calc(100% - 10px) calc(50% + 1px);
  background-size:5px 5px,5px 5px;
  background-repeat:no-repeat}
.bar select:hover{border-color:var(--muted)}
.bar select:focus{border-color:var(--accent)}
/* รายการที่กางออกมาของ <select> ถูกวาดโดยระบบปฏิบัติการ ตั้ง CSS ให้ option
   ไปก็ไม่มีผล (computed style บอกว่าเปลี่ยนแล้ว แต่ popup จริงยังขาวอยู่)
   จึงซ่อน select ไว้ใช้เก็บสถานะอย่างเดียว แล้ววาดรายการเองด้วย div */
.bar select.native{position:absolute;opacity:0;pointer-events:none;width:1px;height:1px}
.bar select option{background:var(--panel);color:var(--fg)}
.sel{position:relative;display:inline-block}
.selbtn{background:var(--bg);color:var(--fg);border:1px solid var(--line);
  border-radius:10px;padding:7px 30px 7px 11px;font-size:.82rem;font-family:inherit;
  cursor:pointer;text-align:left;min-width:120px;position:relative;
  transition:border-color .12s}
.selbtn:hover{border-color:var(--muted)}
.selbtn[aria-expanded=true]{border-color:var(--accent)}
.selbtn::after{content:'';position:absolute;right:11px;top:50%;
  width:0;height:0;margin-top:-2px;
  border-left:4px solid transparent;border-right:4px solid transparent;
  border-top:5px solid currentColor;opacity:.6}
.sellist{position:absolute;z-index:40;top:calc(100% + 5px);left:0;min-width:100%;
  background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:5px;box-shadow:0 8px 24px rgba(0,0,0,.45);white-space:nowrap}
.selopt{padding:7px 12px;border-radius:8px;font-size:.82rem;cursor:pointer;
  color:var(--fg)}
.selopt:hover{background:var(--chip)}
.selopt[aria-selected=true]{color:var(--accent)}
#tip{position:fixed;z-index:90;max-width:340px;pointer-events:none;
  background:var(--panel);color:var(--fg);border:1px solid var(--line);
  border-radius:12px;padding:11px 13px;font-size:.76rem;line-height:1.55;
  white-space:pre-line;box-shadow:0 8px 24px rgba(0,0,0,.45);display:none}
.bar input[type=checkbox]{accent-color:var(--accent);width:15px;height:15px;
  cursor:pointer;margin:0}
.grid{display:grid;gap:14px;
  grid-template-columns:repeat(auto-fill,minmax(310px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  overflow:hidden;display:flex;flex-direction:column;transition:.16s}
.card.dim{opacity:.55}
.thumb{position:relative;aspect-ratio:460/215;background:var(--chip)}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.rankbadge{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.78);
  color:#fff;border-radius:8px;padding:3px 8px;font-size:.72rem;font-weight:600;
  font-family:var(--mono)}
.pricebadge{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.78);
  color:#fff;border-radius:8px;padding:3px 8px;font-size:.75rem;font-weight:600;
  font-family:var(--mono)}
.pricebadge .off{color:#a3e635}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:9px;flex:1}
.name{font-weight:650;font-size:.98rem;letter-spacing:-.01em}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{background:var(--chip);border-radius:7px;padding:2px 8px;font-size:.7rem;
  color:var(--muted);white-space:nowrap}
.chip.single{color:var(--ok)}
.chip.multi{color:var(--cool)}
.chip.pvp{color:var(--warm)}
.metrics{display:flex;gap:14px;align-items:flex-end;margin-top:auto}
.ccu b{font-size:1.15rem;display:block;line-height:1.15;
  font-family:var(--mono);font-weight:700;letter-spacing:-.02em}
.ccu span{font-size:.7rem;color:var(--muted)}
.delta{font-size:.78rem;font-weight:600}
.up{color:var(--ok)} .down{color:var(--muted)} .new{color:var(--hot)}
.spark{margin-left:auto}
.surge{display:flex;align-items:center;gap:7px;font-size:.75rem;color:var(--muted);
  border-top:1px solid var(--line);padding-top:9px}
.score{font-weight:750;font-size:1rem;font-family:var(--mono);
  letter-spacing:-.02em}
/* สามระดับด้วยน้ำหนักสี ไม่ใช่สามสี — ส้มคือ "ร้อนพอให้หยุดดู" เท่านั้น */
.s-hot{color:var(--warm)} .s-warm{color:var(--fg)} .s-mild{color:var(--dim)}
.basis{background:var(--chip);border-radius:6px;padding:2px 8px;font-size:.68rem;
  color:var(--dim)}
.notes{font-size:.73rem;color:var(--dim);display:flex;flex-direction:column;gap:3px}
.blocked{color:var(--warm)}
.empty{text-align:center;color:var(--muted);padding:60px 20px}
.views{display:flex;gap:6px;margin-bottom:14px}
.viewbtn{background:var(--panel);border:1px solid var(--line);color:var(--muted);
  border-radius:10px;padding:7px 15px;font-size:13.5px;font-weight:600;
  font-family:inherit;cursor:pointer;transition:.13s}
.viewbtn:hover{border-color:#454952;color:var(--fg)}
.viewbtn[aria-pressed=true]{background:var(--accent);color:#08130c;
  border-color:transparent}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  padding:20px;margin-bottom:22px}
.panel h2{font-size:11px;margin:0 0 6px;font-weight:700;color:var(--accent);
  letter-spacing:.18em;text-transform:uppercase}
.panel p{margin:0 0 14px;color:var(--dim);font-size:12.5px}
.chartwrap{width:100%}
#chart text,#bars text{font-family:var(--mono);letter-spacing:-.02em}
/* หัวพาเนลกราฟแท่ง: ชื่อซ้าย ปุ่มช่วงเวลาขวา บรรทัดเดียวกัน */
.panelhead{display:flex;align-items:center;justify-content:space-between;
  gap:12px;flex-wrap:wrap;margin-bottom:6px}
.panelhead h2{margin:0}
.ranges{display:flex;gap:5px}
.rangebtn{background:var(--chip);border:1px solid var(--line);color:var(--muted);
  border-radius:9px;padding:5px 13px;font-size:12.5px;font-weight:700;
  font-family:var(--mono);cursor:pointer;transition:.13s}
.rangebtn:hover:not(:disabled){border-color:#454952;color:var(--fg)}
.rangebtn[aria-pressed=true]{background:var(--accent);color:#08130c;
  border-color:transparent}
.rangebtn:disabled{opacity:.32;cursor:not-allowed}
/* ป้ายเตือนว่าช่วงที่เลือกยังเก็บข้อมูลไม่ครบ — ต้องเห็นชัดติดกับกราฟ
   ไม่ใช่ไปกองรวมกับ warn ด้านบนที่คนเลื่อนผ่าน */
.partial{display:inline-block;background:var(--chip);color:var(--warm);
  border:1px solid var(--line);border-left:3px solid var(--warm);
  border-radius:8px;padding:5px 10px;font-size:12px;margin-bottom:10px}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:.75rem}
.legend span{display:flex;align-items:center;gap:6px;color:var(--muted)}
.legend i{width:11px;height:3px;border-radius:2px;display:inline-block}
table.rank{width:100%;border-collapse:collapse;font-size:.85rem}
table.rank th{text-align:left;font-weight:500;color:var(--muted);font-size:.75rem;
  padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
table.rank td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
table.rank tr:last-child td{border-bottom:none}
table.rank a{color:inherit;text-decoration:none}
table.rank a:hover{text-decoration:underline}
.num{text-align:right;font-family:var(--mono);letter-spacing:-.02em;
  white-space:nowrap}
.pos{color:var(--dim);font-family:var(--mono);width:38px}
.rthumb{width:72px;height:34px;object-fit:cover;border-radius:4px;display:block}
a.card{text-decoration:none;color:inherit}
a.card:hover{border-color:#3a3d44;transform:translateY(-2px)}
.warn{background:var(--chip);border:1px solid var(--line);
  border-left:3px solid var(--warm);
  border-radius:12px;padding:13px 15px;margin-bottom:20px;font-size:.84rem}
</style>

<div class="wrap">
  <p class="eyebrow">Steam · 499k Rental Market</p>
  <h1>Game Radar</h1>
  <!-- ทั้งหน้าวาดด้วย JS จากข้อมูลที่ฝังเป็น JSON ถ้าเปิดในตัวที่ไม่รันสคริปต์
       จะได้หน้าเปล่า ๆ กับ dropdown ของ OS ซึ่งดูเหมือนหน้าพัง ต้องบอกให้ชัด -->
  <noscript>
    <div class="warn">หน้านี้สร้างการ์ดและกราฟด้วย JavaScript จากข้อมูลที่ฝังไว้ในไฟล์
      — ตัวที่คุณเปิดอยู่ไม่ได้รันสคริปต์ จึงเห็นแค่โครงหน้า ไม่มีการ์ดและไม่มีกราฟ
      และช่องตัวเลือกจะเป็นกล่องของระบบปฏิบัติการ (มุมเหลี่ยม แถบเลือกสีน้ำเงิน)
      แทนของที่ออกแบบไว้ · เปิดไฟล์นี้ด้วยเบราว์เซอร์ปกติแล้วจะเห็นครบ</div>
  </noscript>
  <div class="sub" id="sub"></div>
  <div id="warn"></div>
  <div class="stats" id="stats"></div>

  <div class="panel" id="barpanel">
    <div class="panelhead">
      <h2>ผู้เล่นรวมตามเวลา</h2>
      <div class="ranges" id="ranges">
        <button class="rangebtn" data-r="1d" aria-pressed="true">1d</button>
        <button class="rangebtn" data-r="7d" aria-pressed="false">7d</button>
        <button class="rangebtn" data-r="30d" aria-pressed="false">30d</button>
      </div>
    </div>
    <p id="barhint"></p>
    <div id="barpartial"></div>
    <div class="chartwrap" id="bars"></div>
  </div>

  <div class="panel" id="chartpanel">
    <h2>ดัชนีผู้เล่นรายเกม</h2>
    <p id="charthint"></p>
    <div class="chartwrap" id="chart"></div>
    <div class="legend" id="legend"></div>
  </div>

  <div class="views">
    <button class="viewbtn" id="vCards" aria-pressed="true">การ์ด</button>
    <button class="viewbtn" id="vRank" aria-pressed="false">อันดับผู้เล่น</button>
  </div>

  <div class="bar">
    <input type="search" id="q" placeholder="ค้นชื่อเกม..." style="min-width:170px">
    <label><input type="checkbox" id="fOpp" checked> เฉพาะเกมที่น่าซื้อ</label>
    <label><input type="checkbox" id="fUnstocked"> ยังไม่มีใครสต็อก</label>
    <label>อายุเกม
      <select id="fFresh">
        <option value="all">ทั้งหมด</option>
        <option value="upcoming">ยังไม่วางขาย</option>
        <option value="fresh">ออกไม่เกิน 1 ปี</option>
        <option value="recent">1-2 ปี</option>
        <option value="evergreen">เก่าแต่ขายได้ตลอด</option>
        <option value="old">เกิน 2 ปี</option>
      </select>
    </label>
    <label>ผู้เล่น
      <select id="fMode">
        <option value="all">ทั้งหมด</option>
        <option value="coop">มี Co-op</option>
        <option value="multi">มี Multi-player</option>
        <option value="single">Single-player ล้วน</option>
      </select>
    </label>
    <label>ชั่วโมงเล่น
      <select id="fPlay">
        <option value="all">ทั้งหมด</option>
        <option value="short">สั้น ไม่เกิน 10 ชม.</option>
        <option value="mid">10-40 ชม.</option>
        <option value="long">เกิน 40 ชม.</option>
        <option value="none">ยังไม่มีข้อมูล</option>
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
        <option value="opp">คะแนนน่าซื้อ</option>
        <option value="surge">คะแนนกระแส</option>
        <option value="stock">คู่แข่งสต็อกน้อยสุด</option>
        <option value="ccu">คนเล่นตอนนี้</option>
        <option value="price">ราคาถูกสุด</option>
      </select>
    </label>
  </div>

  <div class="grid" id="grid"></div>
  <div id="ranktable" hidden></div>
  <div class="empty" id="empty" hidden>ไม่มีเกมที่ตรงเงื่อนไข</div>
</div>

<script>
const DATA = __DATA__;
const META = __META__;
const BASIS = __BASIS__;
const TOTALS = __TOTALS__;

const nf = new Intl.NumberFormat('th-TH');
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const baht = c => c == null ? '—' : '฿' + nf.format(Math.round(c / 100));

document.getElementById('sub').textContent =
  'สแกนล่าสุด ' + META.scanned_at + ' · ' + META.total + ' เกมในเรดาร์ · Steam ' +
  META.scans + ' รอบ · ตลาดเช่า ' + META.market_scans + ' รอบ';

document.getElementById('stats').innerHTML = [
  ['น่าซื้อ', META.opportunities],
  ['ยังไม่มีใครสต็อก', META.unstocked],
  ['ยังไม่วางขาย', META.upcoming],
  ['ไอดีของคุณ', META.mine],
].map(([k, v]) => '<div class="stat"><b>' + nf.format(v) + '</b><span>' + k +
  '</span></div>').join('');

const warns = [];
if (META.scans < 4) {
  warns.push('<b>ข้อมูล Steam ยังไม่พอ</b> — เก็บมา ' + META.scans + ' รอบ ' +
    'คะแนนกระแสยังใช้อันดับรายสัปดาห์ที่ Steam ให้มา ซึ่งหยาบกว่าการเทียบประวัติจริง ' +
    'ครบ 4 รอบเมื่อไหร่ระบบสลับฐานเอง');
}
if (META.market_scans < 2) {
  warns.push('<b>ข้อมูลตลาดยังไม่พอ</b> — เก็บมา ' + META.market_scans + ' รอบ ' +
    'ยังบอกไม่ได้ว่าคู่แข่งกำลังเพิ่มสต็อกเกมไหน ต้องมีอย่างน้อย 2 รอบ');
}
if (warns.length) {
  document.getElementById('warn').innerHTML =
    warns.map(w => '<div class="warn">' + w + '</div>').join('');
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

const NL = String.fromCharCode(10);

function fmtStamp(iso) {
  const d = new Date(iso);
  const p = n => String(n).padStart(2, '0');
  return [p(d.getDate()) + '/' + p(d.getMonth() + 1),
          p(d.getHours()) + ':' + p(d.getMinutes())];
}

// ป้ายอายุเกมแบบละเอียดรายวัน ใช้แทนถังหยาบ ๆ เดิม
function ageLabel(d) {
  if (d.is_evergreen) return ['ขายได้ตลอด', 'multi'];
  if (d.days_until_release != null) {
    const n = d.days_until_release;
    if (n <= 0) return ['กำลังจะขาย', 'pvp'];
    if (n < 60) return ['อีก ' + n + ' วันขาย', 'pvp'];
    return ['อีก ~' + Math.round(n / 30) + ' เดือนขาย', 'pvp'];
  }
  if (d.freshness === 'upcoming') return ['ยังไม่ประกาศวันขาย', 'pvp'];
  const a = d.age_days;
  if (a == null) return ['ไม่รู้วันวางขาย', ''];
  if (a === 0) return ['ออกวันนี้', 'single'];
  if (a < 60) return ['ออกมา ' + a + ' วัน', 'single'];
  if (a < 730) return ['ออกมา ' + Math.round(a / 30) + ' เดือน', a < 365 ? 'single' : ''];
  return ['ออกมา ' + Math.floor(a / 365) + ' ปี', ''];
}
const steamUrl = id => 'https://store.steampowered.com/app/' + id + '/';

function breakdown(d) {
  const p = d.score_parts || {};
  if (!p.steps || !p.steps.length) {
    return 'คะแนน 0 — ' + (p.reason || 'ไม่เข้าเกณฑ์');
  }
  const lines = ['คะแนนน่าซื้อ = ' + d.opportunity_score.toFixed(2), ''];
  p.steps.forEach(([name, val, why], i) => {
    const op = i === 0 ? '   ' : ' × ';
    lines.push(op + name + ' ' + val + '   (' + why + ')');
  });
  lines.push('');
  lines.push('ตัวคูณต่ำกว่า 1 คือหักคะแนน สูงกว่า 1 คือเพิ่ม');
  return lines.join(NL);
}

const FRESH_LABEL = {
  upcoming: ['ยังไม่วางขาย', 'pvp'],
  fresh: ['ออกไม่เกิน 1 ปี', 'single'],
  recent: ['1-2 ปี', ''],
  old: ['เกิน 2 ปี', ''],
  unknown: ['ไม่รู้วันวางขาย', '']
};

function card(d) {
  const modes = [];
  const fl = ageLabel(d);
  if (fl[0]) modes.push('<span class="chip ' + fl[1] + '">' + fl[0] + '</span>');
  if (d.is_coop) modes.push('<span class="chip multi">Co-op</span>');
  else if (d.is_multi) modes.push('<span class="chip multi">Multi-player</span>');
  else if (d.is_single) modes.push('<span class="chip">Single-player</span>');
  if (d.is_online_pvp) modes.push('<span class="chip pvp">Online PvP</span>');

  let stock;
  if (d.stocked_mine > 0)
    stock = '<span class="delta up">คุณมี ' + d.stocked_mine + '/' + d.stocked_total + ' ใบ</span>';
  else if (d.stocked_total === 0)
    stock = '<span class="delta new">ยังไม่มีใครสต็อก</span>';
  else
    stock = '<span class="delta down">คู่แข่งมี ' + d.stocked_total + ' ใบ</span>';
  if (d.stock_delta > 0) stock += ' <span class="delta up">+' + d.stock_delta + '</span>';

  // ชั่วโมงเล่นบอกว่าควรตั้งแพ็กเช่ากี่วัน (แพลตฟอร์มขายเป็น 1/3/7 วัน)
  if (d.playtime_median_h != null) {
    const h = d.playtime_median_h;
    const pack = h <= 10 ? 'เช่า 1 วันพอ' : h <= 40 ? 'เหมาะกับ 3 วัน' : 'ต้องเช่ายาว';
    modes.push('<span class="chip" data-tip="ค่ากลางจากรีวิวล่าสุด ' +
      (d.playtime_sample || 0) + ' คน' + NL + pack + '">เล่น ~' +
      (h < 10 ? h.toFixed(1) : Math.round(h)) + ' ชม.</span>');
  }
  if (d.review_desc) {
    const pct = d.review_ratio != null ? Math.round(d.review_ratio * 100) + '%' : '';
    modes.push('<span class="chip" data-tip="' + esc(d.review_desc) + ' จาก ' +
      nf.format(d.review_total || 0) + ' รีวิว">' + pct + ' ชอบ</span>');
  }

  const disc = d.discount_percent > 0
    ? '<span class="off">-' + d.discount_percent + '%</span> ' : '';
  const b = BASIS[d.surge_basis] || ['—', ''];

  const notes = d.blockers.map(x => '<div class="blocked">⚠ ' + esc(x) + '</div>')
    .concat(d.notes.slice(0, 3).map(n => '<div>· ' + esc(n) + '</div>')).join('');

  const price = d.status === 'upcoming' && d.price_final == null
    ? 'ยังไม่ประกาศราคา' : (d.is_free ? 'ฟรี' : baht(d.price_final));

  return '<a class="card' + (d.opportunity_score > 0 ? '' : ' dim') + '" ' +
    'href="' + steamUrl(d.appid) + '" target="_blank" rel="noopener">' +
    '<div class="thumb">' +
    (d.header_image ? '<img loading="lazy" src="' + esc(d.header_image) + '" alt="">' : '') +
    (d.played_rank ? '<span class="rankbadge">#' + d.played_rank + '</span>' : '') +
    '<span class="pricebadge">' + disc + price + '</span>' +
    '</div><div class="body">' +
    '<div class="name">' + esc(d.name) + '</div>' +
    '<div class="chips">' + modes.join('') + '</div>' +
    '<div class="chips">' + d.genres.map(g => '<span class="chip">' + esc(g) + '</span>').join('') + '</div>' +
    '<div class="metrics"><div class="ccu"><b>' +
    (d.ccu == null ? '—' : nf.format(d.ccu)) +
    '</b><span>คนเล่นตอนนี้</span></div>' + stock + spark(d.history) + '</div>' +
    '<div class="surge"><span class="score ' + scoreClass(d.opportunity_score) +
    '" data-tip="' + esc(breakdown(d)) + '">' + d.opportunity_score.toFixed(1) +
    '</span><span data-tip="' + esc(breakdown(d)) + '">น่าซื้อ</span>' +
    '<span class="basis" data-tip="คะแนนกระแสดิบ' + NL + 'ฐาน: ' + esc(b[0]) + ' — ' + esc(b[1]) + '">' +
    'กระแส ' + d.surge_score.toFixed(1) + '</span></div>' +
    (notes ? '<div class="notes">' + notes + '</div>' : '') +
    '</div></a>';
}

function apply() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const onlyOpp = document.getElementById('fOpp').checked;
  const onlyFree = document.getElementById('fUnstocked').checked;
  const fresh = document.getElementById('fFresh').value;
  const mode = document.getElementById('fMode').value;
  const genre = document.getElementById('fGenre').value;
  const play = document.getElementById('fPlay').value;
  const price = document.getElementById('fPrice').value;
  const sort = document.getElementById('fSort').value;

  const rows = DATA.filter(d => {
    if (q && !d.name.toLowerCase().includes(q)) return false;
    // มุมมองอันดับคือการเรียงตามคนเล่นล้วน ๆ ไม่เอาการตัดสินเรื่องคะแนนมากรอง
    // (ไม่งั้นเกมที่คนเล่นเยอะแต่ระบบให้ 0 จะหายไปจากอันดับทั้งที่มันอยู่อันดับต้น ๆ จริง)
    if (view !== 'rank' && onlyOpp && !(d.opportunity_score > 0)) return false;
    if (onlyFree && d.stocked_total > 0) return false;
    if (fresh === 'evergreen') { if (!d.is_evergreen) return false; }
    else if (fresh !== 'all' && (d.freshness !== fresh || d.is_evergreen)) return false;
    if (mode === 'single' && !(d.is_single && !d.is_multi)) return false;
    if (mode === 'multi' && !d.is_multi) return false;
    if (mode === 'coop' && !d.is_coop) return false;
    if (genre && !d.genres.includes(genre)) return false;
    const ph = d.playtime_median_h;
    if (play === 'short' && !(ph != null && ph <= 10)) return false;
    if (play === 'mid' && !(ph != null && ph > 10 && ph <= 40)) return false;
    if (play === 'long' && !(ph != null && ph > 40)) return false;
    if (play === 'none' && ph != null) return false;
    const p = d.price_final;
    if (price === 'sweet' && !(p >= 10000 && p <= 60000)) return false;
    if (price === 'cheap' && !(p != null && p < 10000)) return false;
    if (price === 'rich' && !(p != null && p > 60000)) return false;
    return true;
  });

  const key = {
    opp: d => -d.opportunity_score,
    surge: d => -d.surge_score,
    stock: d => d.stocked_total,
    ccu: d => -(d.ccu == null ? -1 : d.ccu),
    price: d => d.price_final == null ? Infinity : d.price_final,
  }[sort];
  rows.sort((a, b) => key(a) - key(b) || b.opportunity_score - a.opportunity_score);

  const grid = document.getElementById('grid');
  const rank = document.getElementById('ranktable');
  if (view === 'rank') {
    grid.hidden = true; grid.innerHTML = '';
    rank.hidden = false;
    rank.innerHTML = rankTable(rows);
  } else {
    rank.hidden = true; rank.innerHTML = '';
    grid.hidden = false;
    grid.innerHTML = rows.map(card).join('');
  }
  document.getElementById('empty').hidden = rows.length > 0;
}

// ---------- มุมมองอันดับผู้เล่น ----------
function rankTable(rows) {
  const live = rows.filter(d => d.ccu != null).sort((a, b) => b.ccu - a.ccu);
  if (!live.length) return '<div class="empty">ไม่มีเกมที่วัดผู้เล่นได้</div>';
  const body = live.map((d, i) => {
    let stock;
    if (d.stocked_mine > 0) stock = 'คุณ ' + d.stocked_mine + '/' + d.stocked_total;
    else if (d.stocked_total === 0) stock = '—';
    else stock = d.stocked_total + ' ใบ';
    return '<tr><td class="pos">' + (i + 1) + '</td>' +
      '<td>' + (d.header_image
        ? '<a href="' + steamUrl(d.appid) + '" target="_blank" rel="noopener">' +
          '<img class="rthumb" loading="lazy" src="' + esc(d.header_image) + '" alt=""></a>'
        : '') + '</td>' +
      '<td><a href="' + steamUrl(d.appid) + '" target="_blank" rel="noopener">' +
        esc(d.name) + '</a></td>' +
      '<td class="num">' + nf.format(d.ccu) + '</td>' +
      '<td class="num">' + (d.is_free ? 'ฟรี' : baht(d.price_final)) + '</td>' +
      '<td>' + (d.is_coop ? 'Co-op' : d.is_multi ? 'Multi' : 'Single') + '</td>' +
      '<td class="num">' + stock + '</td>' +
      '<td class="num" data-tip="' + esc(breakdown(d)) + '">' +
        d.opportunity_score.toFixed(1) + '</td></tr>';
  }).join('');
  return '<div class="panel" style="padding:4px 6px"><table class="rank">' +
    '<thead><tr><th>#</th><th></th><th>เกม</th><th class="num">คนเล่นตอนนี้</th>' +
    '<th class="num">ราคา</th><th>โหมด</th><th class="num">สต็อกตลาด</th>' +
    '<th class="num">น่าซื้อ</th></tr></thead><tbody>' + body + '</tbody></table></div>';
}

// ---------- กราฟแท่ง: ผู้เล่นรวมตามเวลา (1d / 7d / 30d) ----------
// พล็อตค่าดิบ ไม่ใช่ดัชนี เพราะเป็นตัวเลขเดียวกันทั้งกราฟ (ผลรวมของตะกร้าเกมชุดเดิม)
// เทียบแท่งต่อแท่งได้ตรง ๆ อยู่แล้ว ไม่ต้องแปลงฐาน
// แกนตั้งเริ่มที่ 0 เสมอ — กราฟแท่งที่ตัดฐานทิ้งจะโกหกสัดส่วนความสูง
const RANGE_LABEL = { '1d': '24 ชั่วโมง', '7d': '7 วัน', '30d': '30 วัน' };
// เริ่มที่ 1d แต่ถ้าช่วงนั้นยังมีไม่ถึงสองจุด ให้ตกไปช่วงแรกที่มีข้อมูลจริง
let range = ['1d', '7d', '30d'].find(r => TOTALS[r]) || '1d';

function drawBars() {
  const panel = document.getElementById('barpanel');
  const win = TOTALS[range];
  if (!win || win.points.length < 2) { panel.hidden = true; return; }
  panel.hidden = false;

  const pts = win.points;
  const hi = Math.max(...pts.map(p => p[1]));

  document.getElementById('barhint').textContent =
    'ผลรวมผู้เล่นพร้อมกันของเกมชุดเดียวกัน ' + nf.format(win.basket) + ' เกม ' +
    'ที่เก็บได้ครบทุกรอบในช่วงนี้ · ' + pts.length + ' รอบสแกน · ' +
    'ย้อนหลังจากรอบล่าสุด ไม่ใช่จากเวลาปัจจุบัน';

  document.getElementById('barpartial').innerHTML = win.full ? '' :
    '<div class="partial">ยังเก็บข้อมูลไม่ครบ ' + RANGE_LABEL[range] +
    ' — ที่มีจริงคือ ' + fmtSpan(win.span_h) + ' แท่งที่เห็นคือทั้งหมดที่มี</div>';

  const W = 900, H = 280, L = 58, R = 14, T = 14, B = 44;
  const plotW = W - L - R, plotH = H - T - B;
  // ความกว้างแท่งคิดจากจำนวนแท่ง ไม่ใช่จากเวลาจริง — ต่างจากกราฟเส้นด้านล่าง
  // ที่ต้องเว้นตามเวลาเพราะความชันคือความหมาย ส่วนแท่งอ่านที่ความสูง
  // ถ้าวางตามเวลาจริง สองรอบที่ห่างกันนาทีเดียวจะกลายเป็นแท่งบางเฉียบซ้อนกัน
  const slot = plotW / pts.length;
  const bw = Math.max(2, Math.min(46, slot * 0.66));
  const ytop = hi * 1.08 || 1;
  const ys = v => T + (1 - v / ytop) * plotH;

  let svg = '<svg width="100%" viewBox="0 0 ' + W + ' ' + H +
    '" preserveAspectRatio="xMidYMid meet" style="display:block" ' +
    'role="img" aria-label="ผู้เล่นรวมตามเวลา ช่วง ' + RANGE_LABEL[range] + '">';

  // เส้นกริดแนวนอน 4 ระดับ ติดป้ายแบบย่อ (1.2M) ให้แกนไม่กินที่
  for (let i = 0; i <= 4; i++) {
    const v = (ytop / 4) * i, y = ys(v);
    svg += '<line x1="' + L + '" y1="' + y.toFixed(1) + '" x2="' + (W - R) +
      '" y2="' + y.toFixed(1) + '" stroke="currentColor" stroke-width="0.5" ' +
      'opacity="' + (i === 0 ? '0.3' : '0.12') + '"/>';
    svg += '<text x="' + (L - 8) + '" y="' + (y + 4).toFixed(1) + '" font-size="11" ' +
      'fill="currentColor" opacity="0.45" text-anchor="end">' + short(v) + '</text>';
  }

  let labelX = -Infinity;
  pts.forEach(([t, v], i) => {
    const cx = L + slot * (i + 0.5);
    const y = ys(v);
    svg += '<rect x="' + (cx - bw / 2).toFixed(1) + '" y="' + y.toFixed(1) +
      '" width="' + bw.toFixed(1) + '" height="' + Math.max(1, H - B - y).toFixed(1) +
      '" rx="2" fill="var(--accent)" opacity="' +
      (i === pts.length - 1 ? '1' : '0.62') + '"><title>' +
      fmtStamp(t).join(' ') + ' · ' + nf.format(v) + ' คน</title></rect>';
    // ป้ายเวลาเว้นตามระยะพิกเซล และกันป้ายแท่งสุดท้าย (= ล่าสุด) ไว้เสมอ
    const isLast = i === pts.length - 1;
    if (!isLast && (cx - labelX < 74 || (L + slot * (pts.length - 0.5)) - cx < 74)) return;
    labelX = cx;
    const [d1, d2] = fmtStamp(t);
    svg += '<text x="' + cx.toFixed(1) + '" y="' + (H - B + 17) + '" font-size="11" ' +
      'fill="currentColor" opacity="0.65" text-anchor="middle">' + d1 + '</text>';
    svg += '<text x="' + cx.toFixed(1) + '" y="' + (H - B + 30) + '" font-size="10" ' +
      'fill="currentColor" opacity="0.4" text-anchor="middle">' + d2 + '</text>';
  });
  svg += '</svg>';
  document.getElementById('bars').innerHTML = svg;
}

function fmtSpan(h) {
  return h < 48 ? h.toFixed(1) + ' ชั่วโมง' : (h / 24).toFixed(1) + ' วัน';
}
function short(v) {
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return Math.round(v / 1e3) + 'k';
  return String(Math.round(v));
}

// ปุ่มช่วงที่ยังไม่มีข้อมูลเลย ปิดไปเลยดีกว่าปล่อยให้กดแล้วกราฟหาย
document.querySelectorAll('#ranges .rangebtn').forEach(b => {
  const r = b.dataset.r;
  b.setAttribute('aria-pressed', String(r === range));
  if (!TOTALS[r]) { b.disabled = true; b.title = 'ยังไม่มีข้อมูลในช่วงนี้'; return; }
  b.addEventListener('click', () => {
    range = r;
    document.querySelectorAll('#ranges .rangebtn').forEach(o =>
      o.setAttribute('aria-pressed', String(o.dataset.r === r)));
    drawBars();
  });
});

// ---------- กราฟเส้น: ดัชนีผู้เล่น ฐาน 100 ----------
// ใช้ดัชนีแทนค่าดิบ เพราะเกมใหญ่กับเกมเล็กต่างกันหลักแสน ถ้าพล็อตค่าดิบ
// เส้นของเกมเล็กจะแบนติดพื้นจนมองไม่เห็นว่ามันกำลังพุ่ง
// นำด้วยสองสีของธีม (เขียว/ส้ม) แล้วต่อด้วยสีที่ความสว่างใกล้กัน
// เพื่อไม่ให้เส้นไหนเด่นกว่าเส้นอื่นด้วยตัวสีเอง — ความเด่นควรมาจากรูปทรงของเส้น
const LINE_COLORS = ['#4ade80','#ff8a4c','#60a5fa','#c084fc',
                     '#22d3ee','#f472b6','#facc15','#94a3b8'];

function drawChart() {
  const pool = DATA.filter(d => d.series && d.series.length >= 2);
  const stamps = [...new Set(pool.flatMap(d => d.series.map(p => p[0])))].sort();
  const hint = document.getElementById('charthint');

  if (stamps.length < 2) {
    document.getElementById('chartpanel').hidden = true;
    return;
  }
  const picked = pool
    .filter(d => d.opportunity_score > 0 || d.stocked_total > 0)
    .sort((a, b) => b.ccu - a.ccu).slice(0, 8);
  if (!picked.length) { document.getElementById('chartpanel').hidden = true; return; }

  hint.textContent = 'เทียบค่ากลางของเกมนั้นเอง = 100 · แกนตั้งเป็น log ' +
    '(200 กับ 50 ห่างจาก 100 เท่ากัน) · แกนเวลาเว้นตามจริง · ' + stamps.length + ' จุดข้อมูล';

  const W = 900, H = 280, L = 46, R = 14, T = 14, B = 44;
  // แกน x เว้นตามเวลาจริง ไม่ใช่ลำดับที่ของ scan
  // ตอนใช้ลำดับ สอง scan ที่ห่างกัน 1 นาที (20:18 กับ 20:19) กินพื้นที่เท่ากับ
  // ช่วงที่ห่างกัน 4.5 ชม. ความชันของเส้นเลยสื่อความหมายไม่ได้เลย
  const ms = t => Date.parse(t);
  const t0 = ms(stamps[0]), tSpan = (ms(stamps[stamps.length - 1]) - t0) || 1;
  const xs = t => L + ((ms(t) - t0) / tSpan) * (W - L - R);
  // ฐาน 100 = ค่ากลางของเกมนั้นเอง ไม่ใช่จุดแรก
  // จุดแรกที่เก็บได้บังเอิญตกตอน 20:18 = prime time เอเชีย = ใกล้ยอดของวัน
  // ทุกเส้นเลยถูกเทียบกับพีคตัวเองแล้วจมใต้ 100 ตลอด ทั้งที่ไม่ได้ตกจริง
  const med = arr => {
    const v = [...arr].sort((a, b) => a - b), m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  };
  const series = picked.map(d => {
    const base = med(d.series.map(pt => pt[1]).filter(c => c > 0)) || 1;
    return { name: d.name, appid: d.appid,
             pts: d.series.map(([t, c]) => [t, (Math.max(c, 1) / base) * 100]) };
  });
  const vals = series.flatMap(s => s.pts.map(p => p[1])).concat([100]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  // แกน y เป็น log เพราะสิ่งที่พล็อตคือ "อัตราส่วน" ไม่ใช่ค่าดิบ
  // โตเป็น 2 เท่า กับเหลือครึ่งเดียว ต้องห่างจากเส้น 100 เท่ากันคนละฝั่ง
  // ถ้าใช้เส้นตรง ตัวที่พุ่งจะกินพื้นที่จนตัวอื่นแบนติดกัน
  // (How to Fish แตะ 258 ทำให้อีก 7 เส้นถูกบีบอยู่แค่ช่วง 56-180)
  const pad = 1.09;
  const ly0 = Math.log(lo / pad), ly1 = Math.log(hi * pad);
  const ys = v => T + (1 - (Math.log(v) - ly0) / (ly1 - ly0)) * (H - T - B);
  // ขีดกริดตามบันไดอัตราส่วน (ครึ่ง · สองเท่า · สามเท่า) ไม่ใช่ระยะเท่า ๆ กัน
  const LADDER = [10, 15, 20, 25, 33, 50, 67, 100, 150, 200, 300, 400, 600, 1000];
  const gridv = LADDER.filter(v => v >= lo / pad && v <= hi * pad);

  // width 100% + viewBox ให้กราฟย่อขยายตามกล่อง ไม่ต้องมีแถบเลื่อนแนวนอน
  // และป้ายแกนขวาสุดไม่โดนตัด
  let svg = '<svg width="100%" viewBox="0 0 ' + W + ' ' + H +
    '" preserveAspectRatio="xMidYMid meet" style="display:block" ' +
    'role="img" aria-label="ดัชนีผู้เล่นตามเวลา">';
  gridv.forEach(v => {
    if (v !== 100) {
      svg += '<line x1="' + L + '" y1="' + ys(v).toFixed(1) + '" x2="' + (W - R) +
        '" y2="' + ys(v).toFixed(1) +
        '" stroke="currentColor" stroke-width="0.5" opacity="0.12"/>';
    }
    svg += '<text x="8" y="' + (ys(v) + 4).toFixed(1) + '" font-size="11" ' +
      'fill="currentColor" opacity="' +
      (v === 100 ? '0.7' : '0.42') + '">' + v + '</text>';
  });
  svg += '<line x1="' + L + '" y1="' + ys(100).toFixed(1) + '" x2="' + (W - R) +
    '" y2="' + ys(100).toFixed(1) + '" stroke="currentColor" stroke-width="1" ' +
    'stroke-dasharray="3 3" opacity="0.35"/>';

  // แกนเวลา: ขีดที่ทุกจุดที่เก็บจริง แต่ติดป้ายแค่บางจุดไม่ให้ตัวหนังสือชนกัน
  // พอแกนเป็นเวลาจริง จะนับ "ทุก N จุด" ไม่ได้แล้ว เพราะจุดที่ห่างกันนาทีเดียว
  // จะทับกันสนิท ต้องวัดเป็นระยะพิกเซลจริง และกันป้ายสุดท้าย (= ล่าสุด) ไว้เสมอ
  const lastX = xs(stamps[stamps.length - 1]);
  let labelX = -Infinity;
  stamps.forEach((t, i) => {
    const x = xs(t);
    svg += '<line x1="' + x.toFixed(1) + '" y1="' + T + '" x2="' + x.toFixed(1) +
      '" y2="' + (H - B) + '" stroke="currentColor" stroke-width="0.5" opacity="0.08"/>';
    svg += '<line x1="' + x.toFixed(1) + '" y1="' + (H - B) + '" x2="' + x.toFixed(1) +
      '" y2="' + (H - B + 4) + '" stroke="currentColor" stroke-width="0.5" opacity="0.35"/>';
    const isLast = i === stamps.length - 1;
    if (!isLast && (x - labelX < 70 || lastX - x < 70)) return;
    labelX = x;
    const [d1, d2] = fmtStamp(t);
    svg += '<text x="' + x.toFixed(1) + '" y="' + (H - B + 17) +
      '" font-size="11" fill="currentColor" opacity="0.65" text-anchor="middle">' +
      d1 + '</text>';
    svg += '<text x="' + x.toFixed(1) + '" y="' + (H - B + 30) +
      '" font-size="10" fill="currentColor" opacity="0.4" text-anchor="middle">' +
      d2 + '</text>';
  });
  series.forEach((s, i) => {
    const pts = s.pts.map(([t, v]) => xs(t).toFixed(1) + ',' + ys(v).toFixed(1)).join(' ');
    svg += '<polyline points="' + pts + '" fill="none" stroke="' +
      LINE_COLORS[i % LINE_COLORS.length] + '" stroke-width="1.8" ' +
      'stroke-linejoin="round" stroke-linecap="round"/>';
  });
  svg += '</svg>';
  document.getElementById('chart').innerHTML = svg;
  document.getElementById('legend').innerHTML = series.map((s, i) => {
    const last = s.pts[s.pts.length - 1][1];
    return '<span><i style="background:' + LINE_COLORS[i % LINE_COLORS.length] + '"></i>' +
      '<a href="' + steamUrl(s.appid) + '" target="_blank" rel="noopener" ' +
      'style="color:inherit;text-decoration:none">' + esc(s.name) + '</a> ' +
      '<b style="font-family:var(--mono);font-weight:700;color:var(--fg)">' +
      last.toFixed(0) + '</b></span>';
  }).join('');
}

let view = 'cards';
function setView(v) {
  view = v;
  document.getElementById('vCards').setAttribute('aria-pressed', String(v === 'cards'));
  document.getElementById('vRank').setAttribute('aria-pressed', String(v === 'rank'));
  apply();
}
document.getElementById('vCards').addEventListener('click', () => setView('cards'));
document.getElementById('vRank').addEventListener('click', () => setView('rank'));

['q', 'fOpp', 'fUnstocked', 'fFresh', 'fMode', 'fGenre', 'fPlay', 'fPrice', 'fSort'].forEach(id =>
  document.getElementById(id).addEventListener('input', apply));
// ---------- dropdown ที่เราวาดเอง ----------
// native <select> ใช้ popup ของ OS ซึ่งจัดสไตล์ไม่ได้ (ยืนยันแล้วว่าเป็นกล่องขาว
// ในธีมมืดถึงจะตั้ง CSS ให้ option ก็ตาม) จึงเก็บ select ไว้เป็นแหล่งสถานะอย่างเดียว
// แล้ววาด UI เอง เพื่อไม่ต้องแก้ตรรกะ apply() ที่อ่านค่าจาก select อยู่แล้ว
function enhanceSelect(sel) {
  // <label> ที่ห่อ select อยู่จะ "ส่งต่อคลิก" ไปเปิด popup ของ OS ทันทีที่คลิกปุ่ม
  // ที่เราวาดเอง เพราะปุ่มอยู่ข้างในตัว label ด้วย — ซ่อน select ไว้ก็ไม่ช่วย
  // (pointer-events ไม่เกี่ยว label สั่งเปิดตัวควบคุมตรง ๆ ไม่ได้ผ่าน pointer)
  // แก้ที่โครงสร้าง: เปลี่ยน <label> เป็น <span> ไปเลย ไม่มี label = ไม่มีการส่งต่อ
  const lab = sel.closest('label');
  if (lab) {
    const span = document.createElement('span');
    span.className = ('fld ' + lab.className).trim();
    span.style.cssText = lab.style.cssText;
    while (lab.firstChild) span.appendChild(lab.firstChild);
    lab.replaceWith(span);
  }
  sel.classList.add('native');
  const wrap = document.createElement('span');
  wrap.className = 'sel';
  sel.parentNode.insertBefore(wrap, sel);
  wrap.appendChild(sel);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'selbtn';
  btn.setAttribute('aria-haspopup', 'listbox');
  btn.setAttribute('aria-expanded', 'false');
  wrap.appendChild(btn);

  const list = document.createElement('div');
  list.className = 'sellist';
  list.setAttribute('role', 'listbox');
  list.hidden = true;
  wrap.appendChild(list);

  const sync = () => {
    const o = sel.options[sel.selectedIndex];
    btn.textContent = o ? o.textContent : '';
  };
  const close = () => { list.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
  const open = () => {
    document.querySelectorAll('.sellist').forEach(l => { l.hidden = true; });
    document.querySelectorAll('.selbtn').forEach(b => b.setAttribute('aria-expanded', 'false'));
    list.innerHTML = '';
    [...sel.options].forEach((o, i) => {
      const item = document.createElement('div');
      item.className = 'selopt';
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(i === sel.selectedIndex));
      item.textContent = o.textContent;
      item.addEventListener('click', () => {
        sel.selectedIndex = i;
        sync();
        close();
        sel.dispatchEvent(new Event('input', { bubbles: true }));
      });
      list.appendChild(item);
    });
    list.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
  };

  btn.addEventListener('click', e => {
    e.preventDefault();   // กัน label activation ที่จะไปเปิด popup ของ OS
    e.stopPropagation();
    list.hidden ? open() : close();
  });
  btn.addEventListener('keydown', e => {
    if (e.key === 'Escape') close();
  });
  sync();
}
document.querySelectorAll('.bar select').forEach(enhanceSelect);
document.addEventListener('click', () => {
  document.querySelectorAll('.sellist').forEach(l => { l.hidden = true; });
  document.querySelectorAll('.selbtn').forEach(b => b.setAttribute('aria-expanded', 'false'));
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.sellist').forEach(l => { l.hidden = true; });
  document.querySelectorAll('.selbtn').forEach(b => b.setAttribute('aria-expanded', 'false'));
});

// ---------- tooltip ที่เราวาดเอง ----------
// title= ของเบราว์เซอร์ใช้กล่องของ OS (พื้นเหลือง ตัวดำ) ซึ่งไม่เข้าธีมและ
// หน่วงก่อนโผล่ประมาณหนึ่งวินาที กล่องนี้โผล่ทันทีและใช้สีเดียวกับหน้าเว็บ
const tip = document.createElement('div');
tip.id = 'tip';
document.body.appendChild(tip);
let tipTarget = null;

function placeTip(e) {
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > innerWidth - 8) x = e.clientX - w - pad;
  if (y + h > innerHeight - 8) y = e.clientY - h - pad;
  tip.style.left = Math.max(8, x) + 'px';
  tip.style.top = Math.max(8, y) + 'px';
}
document.addEventListener('mouseover', e => {
  const t = e.target.closest('[data-tip]');
  if (!t || t === tipTarget) return;
  tipTarget = t;
  tip.textContent = t.getAttribute('data-tip');
  tip.style.display = 'block';
  placeTip(e);
});
document.addEventListener('mousemove', e => { if (tipTarget) placeTip(e); });
document.addEventListener('mouseout', e => {
  if (!tipTarget) return;
  if (e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('[data-tip]') === tipTarget) return;
  tipTarget = null;
  tip.style.display = 'none';
});
// กันไม่ให้การคลิกอ่านคะแนนพาไปหน้า Steam
document.addEventListener('click', e => {
  if (e.target.closest('.surge')) { e.preventDefault(); e.stopPropagation(); }
});

drawBars();
drawChart();
apply();
</script>
"""


# ---------- ผลรวมผู้เล่นตามเวลา สำหรับกราฟแท่งอันบนสุด ----------
# สรุปฝั่ง Python ไม่ใช่ JS เพราะต้องอ่าน snapshot ทุกแถว (ไม่ใช่แค่ 40 จุดล่าสุด
# ต่อเกมที่ฝังไปกับการ์ด) ช่วง 30 วันเลยต้องคำนวณตรงนี้
WINDOWS = (("1d", 1), ("7d", 7), ("30d", 30))


def totals_series(conn: sqlite3.Connection) -> dict[str, dict]:
    """ผลรวม CCU ต่อรอบสแกน แยกตามช่วงเวลา 1d/7d/30d

    ใช้ "ตะกร้าเกมเดียวกันทุกจุด" (intersection ของ appid ที่มีครบทุกรอบในช่วงนั้น)
    ไม่ใช่ผลรวมของทุกเกมที่เจอในรอบนั้น ๆ เพราะจำนวนเกมต่อรอบไม่เท่ากัน
    (รอบแรก ๆ ได้ 158 เกม รอบหลังได้ 319) ถ้าบวกดื้อ ๆ กราฟจะกระโดดเพราะ
    "เก็บเกมได้เยอะขึ้น" ไม่ใช่เพราะ "คนเล่นเยอะขึ้น" ซึ่งอ่านผิดความหมายทั้งแท่ง

    ช่วงเวลานับถอยหลังจาก "รอบสแกนล่าสุด" ไม่ใช่เวลาปัจจุบัน — ถ้าเครื่องไม่ได้รัน
    มาสองวัน หน้าต่าง 1d ที่นับจากตอนนี้จะว่างเปล่าทั้งที่มีข้อมูลอยู่
    """
    by_stamp: dict[str, dict[int, int]] = {}
    for r in conn.execute(
        "SELECT taken_at, appid, ccu FROM snapshot WHERE ccu IS NOT NULL"
    ):
        by_stamp.setdefault(r["taken_at"], {})[r["appid"]] = r["ccu"]

    stamps = sorted(by_stamp)
    if len(stamps) < 2:
        return {}

    def at(s: str) -> datetime:
        return datetime.fromisoformat(s)

    latest = at(stamps[-1])
    out: dict[str, dict] = {}
    for key, days in WINDOWS:
        cutoff = latest - timedelta(days=days)
        sel = [s for s in stamps if at(s) >= cutoff]
        if len(sel) < 2:
            continue
        basket: set[int] = set(by_stamp[sel[0]])
        for s in sel[1:]:
            basket &= set(by_stamp[s])
        if not basket:
            continue
        span_h = (at(sel[-1]) - at(sel[0])).total_seconds() / 3600
        out[key] = {
            "points": [[s, sum(by_stamp[s][a] for a in basket)] for s in sel],
            "basket": len(basket),
            "span_h": round(span_h, 1),
            # ครอบคลุมจริงไม่ถึงช่วงที่ขอ = ต้องขึ้นป้ายบอก ไม่งั้นคนอ่านจะนึกว่า
            # เห็นครบ 30 วันแล้วทั้งที่เพิ่งเก็บมาวันเดียว
            "full": span_h >= days * 24 * 0.9,
            "days": days,
        }
    return out


def build(conn: sqlite3.Connection, out_path: Path) -> dict[str, int]:
    rows = db.latest_snapshot_per_title(conn)
    stocked = db.latest_market(conn, "platform")
    mine = db.latest_market(conn, "mine")
    delta = db.market_delta(conn, "platform")

    items: list[Assessment] = []
    for row in rows:
        hist = [c for _, c in db.ccu_history(conn, row["appid"])]
        items.append(assess(conn, row, hist, stocked, mine, delta))

    payload = []
    for row, a in zip(rows, items):
        d = asdict(a)
        d["is_free"] = bool(row["is_free"])
        d["history"] = a.history[-20:]
        # จุดข้อมูลพร้อมเวลา สำหรับกราฟเส้น — เก็บเฉพาะเกมที่มี CCU จริง
        d["series"] = (
            [[t, c] for t, c in db.ccu_series(conn, a.appid, limit=40)]
            if a.ccu is not None
            else []
        )
        payload.append(d)

    scanned_at = rows[0]["taken_at"] if rows else db.utcnow()
    try:
        scanned_at = (
            datetime.fromisoformat(scanned_at).astimezone().strftime("%d/%m/%Y %H:%M")
        )
    except ValueError:
        pass

    opps = [a for a in items if a.opportunity_score > 0]
    meta = {
        "scanned_at": scanned_at,
        "total": len(items),
        "opportunities": len(opps),
        "unstocked": sum(1 for a in opps if a.stocked_total == 0),
        "upcoming": sum(1 for a in items if a.status == "upcoming"),
        # นับจากข้อมูลตลาดตรง ๆ ไม่ใช่จาก items เพราะเกมที่เราสต็อกไว้
        # อาจไม่อยู่ในเรดาร์ (เช่นเกมเก่าที่ไม่เข้าเกณฑ์ค้นหา) แล้วจะหายไปจากยอดรวม
        "mine": sum(mine.values()),
        "scans": db.scan_count(conn),
        "market_scans": db.market_scan_count(conn),
    }

    html = (
        TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
        .replace("__META__", json.dumps(meta, ensure_ascii=False))
        .replace("__BASIS__", json.dumps(BASIS_LABEL, ensure_ascii=False))
        .replace("__TOTALS__", json.dumps(totals_series(conn), ensure_ascii=False))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return meta
