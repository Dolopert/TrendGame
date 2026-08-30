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

from . import db, trend
from .score import Assessment, assess

# รากโปรเจกต์ — ใช้หาโฟลเดอร์ assets/fonts ที่ต้องคัดลอกไปข้างผลลัพธ์
ROOT = Path(__file__).resolve().parents[2]

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
/* Kanit — ไฟล์อยู่ข้าง ๆ HTML ที่ fonts/ ไม่ได้ฝังเป็น base64
   เพราะ docs/index.html ถูกเขียนใหม่วันละ ~5 รอบและ commit ทุกครั้ง
   ถ้าฝังฟอนต์เข้าไฟล์ ทุก commit จะพก 113 KB ติดไปด้วยตลอด
   แยกเป็นไฟล์ = commit ครั้งเดียว แล้วเบราว์เซอร์แคชข้ามหน้าได้ด้วย
   ย่อเหลือเฉพาะละติน+ไทย+สัญลักษณ์ที่ใช้จริง: 840 KB -> 113 KB (ดู assets/fonts) */
@font-face{font-family:Kanit;font-style:normal;font-weight:400;font-display:swap;
  src:url(fonts/kanit-400.woff2) format("woff2")}
@font-face{font-family:Kanit;font-style:normal;font-weight:500;font-display:swap;
  src:url(fonts/kanit-500.woff2) format("woff2")}
@font-face{font-family:Kanit;font-style:normal;font-weight:600;font-display:swap;
  src:url(fonts/kanit-600.woff2) format("woff2")}
@font-face{font-family:Kanit;font-style:normal;font-weight:700;font-display:swap;
  src:url(fonts/kanit-700.woff2) format("woff2")}
@font-face{font-family:Kanit;font-style:normal;font-weight:800;font-display:swap;
  src:url(fonts/kanit-800.woff2) format("woff2")}
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
  --font:Kanit,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "Noto Sans Thai",Arial,sans-serif;
  /* ตัวเลขยังใช้ mono ต่อ — Kanit ไม่ใช่ฟอนต์ความกว้างคงที่ ถ้าเอามาใส่คอลัมน์
     ตัวเลขในตาราง หลักจะไม่ตรงกัน กวาดสายตาเทียบค่าไม่ได้ ซึ่งเป็นงานหลัก
     ของหน้านี้ ฟอนต์จึงแบ่งหน้าที่: Kanit = ข้อความ · mono = ตัวเลข */
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
.surge{display:flex;align-items:center;gap:8px;font-size:.75rem;color:var(--muted);
  border-top:1px solid var(--line);padding-top:10px}
/* "น่าซื้อ" คือตัวเลขเดียวบนการ์ดที่ใช้ตัดสินใจ จึงต้องเด่นกว่าทุกอย่าง
   ทำเป็น badge พื้นอ่อนให้เด้งออกจากพื้นมืด — ส่วนคะแนนรีวิวคงเป็น chip ธรรมดา
   เพราะมันไม่ได้อยู่ในสูตร ถ้าไปเน้นด้วยจะแย่งความหมายกัน */
.score{font-weight:750;font-size:1.15rem;font-family:var(--mono);
  letter-spacing:-.03em;background:var(--chip);border-radius:8px;
  padding:2px 9px;line-height:1.35;display:inline-block}
.slabel{font-weight:700;letter-spacing:.04em}
/* สามระดับด้วยน้ำหนักสี ไม่ใช่สามสี — ส้มคือ "ร้อนพอให้หยุดดู" เท่านั้น */
.s-hot{color:var(--warm);background:rgba(255,138,76,.13)}
.s-warm{color:var(--fg)}
.s-mild{color:var(--dim)}
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
/* แท็บในพาเนล — ใช้ขีดใต้ ไม่ใช่ปุ่มทึบ เพราะปุ่มช่วงเวลาข้าง ๆ กับปุ่มมุมมอง
   ด้านล่างเป็นเขียวทึบอยู่แล้ว ถ้าทำทึบอีกจะแย่งสายตากันสามชั้น */
.ptabs{display:flex;gap:20px;align-items:flex-end}
.ptab{background:none;border:0;padding:0 0 8px;margin:0;font-family:inherit;
  font-size:11px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
  color:var(--dim);cursor:pointer;position:relative;transition:.13s}
.ptab:hover{color:var(--muted)}
.ptab[aria-pressed=true]{color:var(--accent)}
.ptab[aria-pressed=true]::after{content:'';position:absolute;left:0;right:0;
  bottom:0;height:2px;background:var(--accent)}
.tgroup{margin-bottom:24px}
.tgroup:last-child{margin-bottom:2px}
.tgroup h3{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  margin:0 0 8px;color:var(--muted)}
table.trend{width:100%;border-collapse:collapse;font-size:.84rem}
table.trend th{text-align:left;font-weight:500;color:var(--dim);font-size:.72rem;
  padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
table.trend td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
table.trend tr:last-child td{border-bottom:none}
table.trend a{color:inherit;text-decoration:none}
table.trend a:hover{text-decoration:underline}
.tdays{display:flex;align-items:flex-end;gap:3px;height:20px}
.tdays i{width:9px;background:var(--chip);border-radius:2px;display:block;min-height:2px}
.tdays i.last{background:var(--muted)}
.tfall{color:var(--warm)}
.trise{color:var(--accent)}
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
.legend span{display:flex;align-items:center;gap:6px;color:var(--muted);cursor:default}
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
/* แผงรายละเอียด: เลื่อนจากขวา ไม่ใช่ modal กลางจอ เพราะยังเห็นการ์ดอื่นค้างอยู่
   ข้างหลัง กดดูทีละเกมต่อกันได้เร็ว และบนมือถือกลายเป็นเต็มจอเองโดยไม่ต้องเขียนเพิ่ม */
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:80;opacity:0;
  pointer-events:none;transition:opacity .18s}
.scrim.open{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(580px,100vw);z-index:85;
  background:var(--panel);border-left:1px solid var(--line);
  transform:translateX(100%);transition:transform .22s cubic-bezier(.4,0,.2,1);
  overflow-y:auto;overscroll-behavior:contain}
.drawer.open{transform:none}
@media(max-width:640px){.drawer{width:100vw;border-left:0}}
.dhead{position:relative}
.dhead img{width:100%;aspect-ratio:460/215;object-fit:cover;display:block}
.dclose{position:absolute;top:12px;right:12px;width:34px;height:34px;
  border-radius:10px;border:1px solid var(--line);background:rgba(0,0,0,.72);
  color:#fff;font-size:17px;line-height:1;cursor:pointer;font-family:inherit}
.dclose:hover{border-color:#454952}
.dbody{padding:18px 20px 34px;display:flex;flex-direction:column;gap:20px}
.dtitle{font-size:20px;font-weight:750;letter-spacing:-.02em;margin:0}
.dsec h4{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);margin:0 0 9px}
.dsec{border-top:1px solid var(--line);padding-top:16px}
.dsec:first-of-type{border-top:0;padding-top:0}
.dscore{display:flex;align-items:baseline;gap:10px}
.dscore b{font-size:34px;font-weight:800;font-family:var(--mono);letter-spacing:-.03em}
.dsteps{width:100%;border-collapse:collapse;font-size:.82rem;margin-top:10px}
.dsteps td{padding:5px 0;border-bottom:1px solid var(--line);vertical-align:top}
.dsteps tr:last-child td{border-bottom:0}
.dsteps .op{color:var(--dim);font-family:var(--mono);width:22px}
.dsteps .val{font-family:var(--mono);font-weight:700;text-align:right;
  white-space:nowrap;padding-left:10px}
.dsteps .why{color:var(--dim);font-size:.76rem}
.dkv{display:grid;grid-template-columns:auto 1fr;gap:6px 14px;font-size:.84rem}
.dkv dt{color:var(--dim)}
.dkv dd{margin:0;font-family:var(--mono);letter-spacing:-.02em}
.dnote{font-size:.8rem;color:var(--muted);display:flex;flex-direction:column;gap:5px}
.dbtn{display:block;text-align:center;background:var(--accent);color:#08130c;
  border-radius:10px;padding:11px;font-weight:700;font-size:13.5px;
  text-decoration:none}
.dbtn:hover{filter:brightness(1.08)}
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
    <div class="panelhead">
      <div class="ptabs" role="tablist">
        <button class="ptab" id="tChart" aria-pressed="true">ดัชนีผู้เล่นรายเกม</button>
        <button class="ptab" id="tTrend" aria-pressed="false">แนวโน้มรายวัน</button>
      </div>
      <div class="ranges" id="cranges">
        <button class="rangebtn" data-r="1d" aria-pressed="true">24hr</button>
        <button class="rangebtn" data-r="7d" aria-pressed="false">7d</button>
        <button class="rangebtn" data-r="30d" aria-pressed="false">30d</button>
        <button class="rangebtn" data-r="all" aria-pressed="false">ทั้งหมด</button>
      </div>
    </div>
    <div id="pageChart">
      <p id="charthint"></p>
      <div id="chartpartial"></div>
      <div class="chartwrap" id="chart"></div>
      <div class="legend" id="legend"></div>
    </div>
    <div id="pageTrend" hidden>
      <p id="trendhint"></p>
      <div id="trendbody"></div>
    </div>
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
  <div class="scrim" id="scrim"></div>
  <aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-hidden="true"></aside>
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
  // ต้องมีรีวิวจริงถึงจะขึ้นป้าย — เดิมเช็คแค่ review_desc ซึ่ง 'No user reviews'
  // ก็ผ่าน แล้วได้ป้าย " ชอบ" ลอยไม่มีตัวเลขบน 121 การ์ด
  // เกมที่ยังไม่มีรีวิวให้ซ่อนไปเลย ไม่ใส่ป้าย "ยังไม่มีคะแนน" เพราะการ์ดแน่นอยู่แล้ว
  // และป้ายที่ไม่ให้ข้อมูลอะไรคือขยะ ไม่ใช่ความสมบูรณ์
  if (d.review_ratio != null && d.review_total > 0) {
    modes.push('<span class="chip" data-tip="' + esc(d.review_desc || '') + ' จาก ' +
      nf.format(d.review_total) + ' รีวิว' + NL +
      'คะแนนรีวิวไม่ได้อยู่ในสูตรคะแนนน่าซื้อ เป็นข้อมูลประกอบ">👍 ' +
      Math.round(d.review_ratio * 100) + '%</span>');
  }

  const disc = d.discount_percent > 0
    ? '<span class="off">-' + d.discount_percent + '%</span> ' : '';
  const b = BASIS[d.surge_basis] || ['—', ''];

  const notes = d.blockers.map(x => '<div class="blocked">⚠ ' + esc(x) + '</div>')
    .concat(d.notes.slice(0, 3).map(n => '<div>· ' + esc(n) + '</div>')).join('');

  const price = d.status === 'upcoming' && d.price_final == null
    ? 'ยังไม่ประกาศราคา' : (d.is_free ? 'ฟรี' : baht(d.price_final));

  // ยังเป็น <a> ที่ชี้ไป Steam อยู่ เพื่อให้คลิกกลาง/ctrl-คลิกเปิดแท็บใหม่ได้ตามปกติ
  // ส่วนคลิกซ้ายธรรมดาถูกดักไปเปิดแผงรายละเอียดแทน (ดู handler ท้ายไฟล์)
  return '<a class="card' + (d.opportunity_score > 0 ? '' : ' dim') + '" ' +
    'data-appid="' + d.appid + '" ' +
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
    '</span><span class="slabel" data-tip="' + esc(breakdown(d)) + '">น่าซื้อ</span>' +
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

// ช่วงเวลาของกราฟเส้น — 24hr กับ 1d คือหน้าต่างเดียวกัน จึงมีปุ่มเดียวชื่อ 24hr
// 'ทั้งหมด' ไว้ดูภาพรวมตั้งแต่วันแรกที่เก็บ ไม่ผูกกับจำนวนวัน
const CHART_WINDOWS = { '1d': 1, '7d': 7, '30d': 30, 'all': null };
const CHART_LABEL = { '1d': '24 ชั่วโมง', '7d': '7 วัน', '30d': '30 วัน', 'all': 'ทั้งหมด' };
let chartRange = '1d';

// เส้นโค้งแบบ monotone cubic (Fritsch-Carlson)
//
// ทำไมไม่ใช้ bezier ธรรมดา: จุดข้อมูลห่างไม่เท่ากันจริง (GitHub Actions หน่วง
// 43 นาที ถึง 3.5 ชม.) เส้นโค้งทั่วไปจะ overshoot คือวาดยอดหรือก้นที่
// *ไม่เคยเกิดขึ้น* ระหว่างจุด ซึ่งอันตรายกับกราฟที่เอาไปตัดสินใจเรื่องเงิน
//
// monotone cubic บีบ tangent ไว้ (เงื่อนไข alpha^2+beta^2 <= 9) จึงการันตีว่า
// ระหว่างสองจุดที่ติดกัน เส้นจะไม่เกินค่าของสองจุดนั้น — โค้งได้แต่ไม่โกหก
function monotonePath(pts) {
  const n = pts.length;
  if (n === 0) return '';
  if (n < 3) return 'M' + pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L');

  const dx = [], dy = [], delta = [];
  for (let i = 0; i < n - 1; i++) {
    dx[i] = pts[i + 1][0] - pts[i][0];
    dy[i] = pts[i + 1][1] - pts[i][1];
    delta[i] = dx[i] === 0 ? 0 : dy[i] / dx[i];
  }
  // ความชันเริ่มต้นที่แต่ละจุด = เฉลี่ยของสองช่วงที่ขนาบอยู่
  const m = [delta[0]];
  for (let i = 1; i < n - 1; i++) m[i] = (delta[i - 1] + delta[i]) / 2;
  m[n - 1] = delta[n - 2];
  // ที่จุดยอด/ก้น (ความชันสองข้างคนละเครื่องหมาย) ต้องบังคับความชันเป็น 0
  // ถ้าไม่ทำ ค่าเฉลี่ยจะพาเส้นพุ่งเลยจุดจริงออกไป — วัดแล้วเกินได้ถึง 8.7px
  // ขั้นนี้คือหัวใจของ Fritsch-Carlson ที่การ clamp ด้านล่างอย่างเดียวแทนไม่ได้
  for (let i = 1; i < n - 1; i++) {
    if (delta[i - 1] * delta[i] <= 0) m[i] = 0;
  }
  // บีบให้ไม่ overshoot: ช่วงที่ราบต้องราบจริง ที่เหลือย่อ tangent ลงในวงกลมรัศมี 3
  for (let i = 0; i < n - 1; i++) {
    if (delta[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / delta[i], b = m[i + 1] / delta[i], sq = a * a + b * b;
    if (sq > 9) {
      const tau = 3 / Math.sqrt(sq);
      m[i] = tau * a * delta[i];
      m[i + 1] = tau * b * delta[i];
    }
  }
  let d = 'M' + pts[0][0].toFixed(1) + ',' + pts[0][1].toFixed(1);
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += 'C' + (pts[i][0] + h).toFixed(1) + ',' + (pts[i][1] + m[i] * h).toFixed(1) +
         ' ' + (pts[i + 1][0] - h).toFixed(1) + ',' +
         (pts[i + 1][1] - m[i + 1] * h).toFixed(1) +
         ' ' + pts[i + 1][0].toFixed(1) + ',' + pts[i + 1][1].toFixed(1);
  }
  return d;
}

function drawChart() {
  const raw = DATA.filter(d => d.series && d.series.length >= 2);
  const allStamps = [...new Set(raw.flatMap(d => d.series.map(p => p[0])))].sort();
  const hint = document.getElementById('charthint');
  const partial = document.getElementById('chartpartial');

  if (allStamps.length < 2) {
    document.getElementById('chartpanel').hidden = true;
    return;
  }

  // ตัดช่วงโดยนับถอยหลังจาก "จุดข้อมูลล่าสุด" ไม่ใช่จากเวลาปัจจุบัน
  // ถ้าไม่ได้สแกนมาสองวัน หน้าต่าง 24hr ที่นับจาก now จะว่างทั้งที่มีข้อมูลอยู่
  const days = CHART_WINDOWS[chartRange];
  const newest = Date.parse(allStamps[allStamps.length - 1]);
  const cut = days == null ? -Infinity : newest - days * 864e5;
  // ต้องตัดที่ series ของแต่ละเกม ไม่ใช่แค่กรอง stamps รวม เพราะฐาน 100
  // คิดจากค่ากลางของจุดที่พล็อตจริง ถ้าไม่ตัด ฐานจะยังอิงข้อมูลนอกช่วงที่เลือก
  const pool = raw
    .map(d => ({ ...d, series: d.series.filter(pt => Date.parse(pt[0]) >= cut) }))
    .filter(d => d.series.length >= 2);
  const stamps = allStamps.filter(t => Date.parse(t) >= cut);

  if (pool.length === 0 || stamps.length < 2) {
    document.getElementById('chartpanel').hidden = true;
    return;
  }
  document.getElementById('chartpanel').hidden = false;

  const picked = pool
    .filter(d => d.opportunity_score > 0 || d.stocked_total > 0)
    .sort((a, b) => b.ccu - a.ccu).slice(0, 8);
  if (!picked.length) { document.getElementById('chartpanel').hidden = true; return; }

  hint.textContent = 'เทียบค่ากลางของเกมนั้นเองในช่วงที่เลือก = 100 · แกนตั้งเป็น log ' +
    '(200 กับ 50 ห่างจาก 100 เท่ากัน) · แกนเวลาเว้นตามจริง · ' + stamps.length + ' จุดข้อมูล';

  // ช่วงที่เก็บข้อมูลจริงไม่ถึงที่ขอ ต้องบอกติดกราฟ ไม่งั้นจะนึกว่าเห็นครบ 30 วัน
  const spanH = (Date.parse(stamps[stamps.length - 1]) - Date.parse(stamps[0])) / 36e5;
  partial.innerHTML = (days != null && spanH < days * 24 * 0.9)
    ? '<div class="partial">ยังเก็บข้อมูลไม่ครบ ' + CHART_LABEL[chartRange] +
      ' — ที่มีจริงคือ ' + fmtSpan(spanH) + ' เส้นที่เห็นคือทั้งหมดที่มี</div>'
    : '';

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
    const xy = s.pts.map(([t, v]) => [xs(t), ys(v)]);
    svg += '<path d="' + monotonePath(xy) + '" fill="none" stroke="' +
      LINE_COLORS[i % LINE_COLORS.length] + '" stroke-width="1.8" ' +
      'stroke-linejoin="round" stroke-linecap="round"/>';
  });
  svg += '</svg>';
  document.getElementById('chart').innerHTML = svg;
  document.getElementById('legend').innerHTML = series.map((s, i) => {
    const last = s.pts[s.pts.length - 1][1];
    const col = LINE_COLORS[i % LINE_COLORS.length];
    // ตัวเลขท้ายชื่อเคยเป็นสีขาวเหมือนกันหมด อ่านเผิน ๆ นึกว่าเป็นคะแนนรีวิว
    // หรือจำนวนผู้เล่น ย้อมสีตามเส้นและติด tooltip บอกให้ชัดว่าคืออะไร
    const tip = esc(s.name) + NL + 'ดัชนีผู้เล่น ' + last.toFixed(0) +
      ' (100 = ระดับปกติของเกมนี้เอง)' + NL +
      (last >= 100 ? 'ตอนนี้คนเล่นมากกว่าปกติ ' + (last - 100).toFixed(0) + '%'
                   : 'ตอนนี้คนเล่นน้อยกว่าปกติ ' + (100 - last).toFixed(0) + '%') +
      NL + 'ไม่ใช่คะแนนรีวิว และไม่ใช่จำนวนผู้เล่น';
    return '<span data-tip="' + tip + '"><i style="background:' + col + '"></i>' +
      '<a href="' + steamUrl(s.appid) + '" target="_blank" rel="noopener" ' +
      'style="color:inherit;text-decoration:none">' + esc(s.name) + '</a> ' +
      '<b style="font-family:var(--mono);font-weight:700;color:' + col + '">' +
      last.toFixed(0) + '</b></span>';
  }).join('');
}

// ปุ่มช่วงของกราฟเส้น — ช่วงไหนมีจุดข้อมูลไม่ถึงสองจุด ปิดปุ่มไปเลย
// ดีกว่าปล่อยให้กดแล้วพาเนลหายไปทั้งอัน
(function () {
  const st = [...new Set(DATA.filter(d => d.series && d.series.length >= 2)
    .flatMap(d => d.series.map(p => p[0])))].sort();
  const newest = st.length ? Date.parse(st[st.length - 1]) : 0;
  const btns = [...document.querySelectorAll('#cranges .rangebtn')];
  const usable = r => {
    const days = CHART_WINDOWS[r];
    if (days == null) return st.length >= 2;
    return st.filter(t => Date.parse(t) >= newest - days * 864e5).length >= 2;
  };
  chartRange = ['1d', '7d', '30d', 'all'].find(usable) || '1d';
  btns.forEach(b => {
    const r = b.dataset.r;
    b.setAttribute('aria-pressed', String(r === chartRange));
    if (!usable(r)) { b.disabled = true; b.title = 'ยังไม่มีข้อมูลในช่วงนี้'; return; }
    b.addEventListener('click', () => {
      chartRange = r;
      btns.forEach(o => o.setAttribute('aria-pressed', String(o.dataset.r === r)));
      drawChart();
    });
  });
})();

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
// ---------- แผงรายละเอียด ----------
// ข้อมูลลึกเคยอยู่แต่ใน tooltip ซึ่งต้องเอาเมาส์ชี้ = บนมือถือเข้าไม่ถึงเลย
// และบันทึกก็ถูกตัดเหลือ 3 บรรทัดบนการ์ด ที่เหลือหายเงียบ ที่นี่แสดงครบ
const scrim = document.getElementById('scrim');
const drawer = document.getElementById('drawer');

// กราฟผู้เล่นของเกมเดียว — ใช้ CCU ดิบได้เพราะไม่ได้เอาไปเทียบข้ามเกม
// แกน x เว้นตามเวลาจริงและใช้เส้นโค้ง monotone เหมือนกราฟใหญ่
function gameChart(pts) {
  if (!pts || pts.length < 2) {
    return '<div class="dnote">ยังมีจุดข้อมูลไม่พอวาดกราฟ</div>';
  }
  const W = 520, H = 150, L = 8, R = 8, T = 12, B = 26;
  const ms = t => Date.parse(t);
  const t0 = ms(pts[0][0]), span = (ms(pts[pts.length - 1][0]) - t0) || 1;
  const vals = pts.map(p => p[1]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.12 || Math.max(hi * 0.08, 1);
  const y0 = lo - pad, y1 = hi + pad;
  const xs = t => L + ((ms(t) - t0) / span) * (W - L - R);
  const ys = v => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
  const xy = pts.map(([t, v]) => [xs(t), ys(v)]);
  const a = fmtStamp(pts[0][0]), b = fmtStamp(pts[pts.length - 1][0]);
  return '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" ' +
    'preserveAspectRatio="xMidYMid meet" style="display:block" ' +
    'role="img" aria-label="ผู้เล่นตามเวลา">' +
    '<path d="' + monotonePath(xy) + '" fill="none" stroke="var(--accent)" ' +
    'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' +
    '<text x="' + L + '" y="' + (H - 8) + '" font-size="10" fill="currentColor" ' +
    'opacity="0.5">' + a[0] + ' ' + a[1] + '</text>' +
    '<text x="' + (W - R) + '" y="' + (H - 8) + '" font-size="10" text-anchor="end" ' +
    'fill="currentColor" opacity="0.5">' + b[0] + ' ' + b[1] + '</text>' +
    '<text x="' + L + '" y="' + (T + 2) + '" font-size="10" fill="currentColor" ' +
    'opacity="0.5">สูงสุด ' + nf.format(hi) + '</text>' +
    '<text x="' + (W - R) + '" y="' + (T + 2) + '" font-size="10" text-anchor="end" ' +
    'fill="currentColor" opacity="0.5">ต่ำสุด ' + nf.format(lo) + '</text>' +
    '</svg>';
}

function drawerSteps(d) {
  const p = d.score_parts || {};
  if (!p.steps || !p.steps.length) {
    return '<div class="dnote">คะแนน 0 — ' + esc(p.reason || 'ไม่เข้าเกณฑ์') + '</div>';
  }
  return '<table class="dsteps">' + p.steps.map(([name, val, why], i) =>
    '<tr><td class="op">' + (i === 0 ? '' : '&times;') + '</td>' +
    '<td>' + esc(name) + '<div class="why">' + esc(why || '') + '</div></td>' +
    '<td class="val">' + val + '</td></tr>').join('') + '</table>';
}

function kvList(rows) {
  return '<dl class="dkv">' + rows.map(r =>
    '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>').join('') + '</dl>';
}

function openDrawer(appid) {
  const d = DATA.find(x => x.appid === appid);
  if (!d) return;
  const price = d.status === 'upcoming' && d.price_final == null
    ? 'ยังไม่ประกาศราคา' : (d.is_free ? 'ฟรี' : baht(d.price_final));
  const k = d.decay;
  const h = d.playtime_median_h;
  const pack = h == null ? null
    : (h <= 10 ? 'เช่า 1 วันพอ' : h <= 40 ? 'เหมาะกับแพ็ก 3 วัน' : 'ต้องเช่ายาว');

  const kv = [['ราคา', price]];
  if (d.ccu != null) kv.push(['คนเล่นตอนนี้', nf.format(d.ccu)]);
  if (d.played_rank) kv.push(['อันดับ Steam', '#' + d.played_rank +
    (d.rank_delta ? ' (' + (d.rank_delta > 0 ? '+' : '') + d.rank_delta +
      ' จากสัปดาห์ก่อน)' : '')]);
  if (d.release_date) kv.push(['วางขาย', esc(d.release_date)]);
  if (d.review_ratio != null && d.review_total > 0) {
    kv.push(['รีวิว', Math.round(d.review_ratio * 100) + '% ชอบ · ' +
      nf.format(d.review_total) + ' รีวิว']);
  }
  if (h != null) {
    kv.push(['ชั่วโมงเล่น', '~' + (h < 10 ? h.toFixed(1) : Math.round(h)) +
      ' ชม. → ' + pack]);
  }
  if (d.rev_per_day != null) {
    kv.push(['รีวิวใหม่/วัน', nf.format(Math.round(d.rev_per_day))]);
  }

  const market = [['คู่แข่งสต็อก', d.stocked_total + ' ใบ'],
    ['ของเรา', d.stocked_mine + ' ใบ' + (d.stocked_total
      ? ' (' + Math.round(d.stocked_mine / d.stocked_total * 100) + '% ของตลาด)' : '')]];
  if (d.stock_delta > 0) market.push(['เพิ่งเพิ่ม', '+' + d.stock_delta + ' ใบ']);

  drawer.innerHTML =
    '<div class="dhead">' +
      (d.header_image ? '<img src="' + esc(d.header_image) + '" alt="">' : '') +
      '<button class="dclose" id="dclose" aria-label="ปิด">&times;</button>' +
    '</div>' +
    '<div class="dbody">' +
      '<h3 class="dtitle">' + esc(d.name) + '</h3>' +

      '<div class="dsec"><h4>คะแนนน่าซื้อ</h4>' +
        '<div class="dscore"><b class="' + scoreClass(d.opportunity_score) + '">' +
        d.opportunity_score.toFixed(1) + '</b>' +
        '<span class="dnote">ฐาน: ' + esc((BASIS[d.surge_basis] || ['—'])[0]) +
        '</span></div>' + drawerSteps(d) + '</div>' +

      '<div class="dsec"><h4>ผู้เล่นตามเวลา</h4>' + gameChart(d.series) + '</div>' +

      (k ? '<div class="dsec"><h4>แนวโน้มรายวัน</h4>' +
        '<div class="dnote">เทียบที่เวลาราว ' + Math.round(k.hour) + ':00 น. ของ ' +
        k.days + ' วัน — <b class="' + (k.per_day < 0 ? 'tfall' : 'trise') + '">' +
        pct(k.per_day) + ' ต่อวัน</b> (รวม ' + pct(k.pct) + ')</div>' +
        kvList(k.points.map(q => [q[0].slice(8, 10) + '/' + q[0].slice(5, 7),
          nf.format(q[1])])) + '</div>' : '') +

      '<div class="dsec"><h4>ข้อมูลเกม</h4>' + kvList(kv) + '</div>' +
      '<div class="dsec"><h4>ตลาดเช่า</h4>' + kvList(market) + '</div>' +

      ((d.notes.length || d.blockers.length) ?
        '<div class="dsec"><h4>บันทึก</h4><div class="dnote">' +
        d.blockers.map(x => '<div class="blocked">&#9888; ' + esc(x) + '</div>').join('') +
        d.notes.map(x => '<div>&middot; ' + esc(x) + '</div>').join('') +
        '</div></div>' : '') +

      '<a class="dbtn" href="' + steamUrl(d.appid) + '" target="_blank" ' +
      'rel="noopener">เปิดหน้า Steam &#8599;</a>' +
    '</div>';

  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  scrim.classList.add('open');
  document.body.style.overflow = 'hidden';
  drawer.scrollTop = 0;
  document.getElementById('dclose').addEventListener('click', closeDrawer);
}

function closeDrawer() {
  drawer.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  scrim.classList.remove('open');
  document.body.style.overflow = '';
}
scrim.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

document.addEventListener('click', e => {
  // กันไม่ให้การคลิกอ่านคะแนนพาไปหน้า Steam
  if (e.target.closest('.surge')) { e.preventDefault(); e.stopPropagation(); return; }
  const card = e.target.closest('a.card');
  if (!card) return;
  // ปล่อยให้ ctrl/cmd/shift/คลิกกลาง เปิดแท็บ Steam ตามพฤติกรรมลิงก์ปกติ
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  openDrawer(Number(card.dataset.appid));
});

// ---------- หน้า "แนวโน้มรายวัน" ----------
// เทียบเกมกับตัวมันเองที่ชั่วโมงไทยเดียวกันคนละวัน — ตัวเลขคิดมาจากฝั่ง Python
// (ดู trend.py) ที่นี่แค่จัดเรียงและวาด
const TREND_MIN_DAYS = 3;   // 2 วันคือลากเส้นผ่านสองจุด ยังไม่เรียกว่าแนวโน้ม
const TREND_MIN_CCU  = 2000; // เกมเล็กเปอร์เซ็นต์แกว่งแรงจนไม่มีความหมาย

function dayBars(pts) {
  const mx = Math.max(...pts.map(p => p[1])) || 1;
  return '<div class="tdays">' + pts.map(([, c], i) =>
    '<i class="' + (i === pts.length - 1 ? 'last' : '') + '" style="height:' +
    Math.max(2, Math.round(c / mx * 20)) + 'px" title="' + nf.format(c) + '"></i>'
  ).join('') + '</div>';
}

function trendRows(list) {
  return '<table class="trend"><thead><tr>' +
    '<th>เกม</th><th>รายวัน</th><th class="num">ล่าสุด</th>' +
    '<th class="num">ต่อวัน</th><th class="num">รวม</th>' +
    '<th class="num">รีวิว/วัน</th><th class="num">น่าซื้อ</th>' +
    '</tr></thead><tbody>' + list.map(d => {
      const k = d.decay, cls = k.per_day < 0 ? 'tfall' : 'trise';
      const last = k.points[k.points.length - 1][1];
      const rv = d.rev_per_day == null ? '—' : nf.format(Math.round(d.rev_per_day));
      return '<tr>' +
        '<td><a href="' + steamUrl(d.appid) + '" target="_blank" rel="noopener">' +
        esc(d.name) + '</a></td>' +
        '<td>' + dayBars(k.points) + '</td>' +
        '<td class="num">' + nf.format(last) + '</td>' +
        '<td class="num ' + cls + '">' + pct(k.per_day) + '</td>' +
        '<td class="num ' + cls + '">' + pct(k.pct) + '</td>' +
        '<td class="num">' + rv + '</td>' +
        '<td class="num">' + d.opportunity_score.toFixed(1) + '</td>' +
        '</tr>';
    }).join('') + '</tbody></table>';
}

function pct(v) { return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%'; }

function drawTrend() {
  const pool = DATA.filter(d => d.decay && d.decay.days >= TREND_MIN_DAYS &&
    d.decay.points[d.decay.points.length - 1][1] >= TREND_MIN_CCU);
  const hint = document.getElementById('trendhint');
  const body = document.getElementById('trendbody');
  if (!pool.length) {
    hint.textContent = '';
    body.innerHTML = '<div class="empty">ยังเทียบไม่ได้ — ต้องมีรอบเก็บที่ชั่วโมง' +
      'ไทยใกล้เคียงกันอย่างน้อย ' + TREND_MIN_DAYS + ' วัน</div>';
    return;
  }
  const days = Math.max(...pool.map(d => d.decay.days));
  const withRev = pool.filter(d => d.rev_per_day != null).length;
  hint.textContent = 'เทียบเกมกับตัวมันเองที่ชั่วโมงไทยเดียวกันคนละวัน — ตัด' +
    'วัฏจักรรายวันที่ทำให้ CCU รวมแกว่ง 1.7 เท่าออก · ' + pool.length + ' เกม · ' +
    'สูงสุด ' + days + ' วัน' +
    (withRev ? ' · มีข้อมูลรีวิว/วันแล้ว ' + withRev + ' เกม'
             : ' · รีวิว/วัน ยังว่าง (เพิ่งเริ่มเก็บประวัติ ต้องรออีก 1-2 วัน)');

  const sorted = [...pool].sort((a, b) => a.decay.per_day - b.decay.per_day);
  const fall = sorted.filter(d => d.decay.per_day < 0).slice(0, 12);
  const rise = sorted.filter(d => d.decay.per_day > 0).slice(-12).reverse();
  body.innerHTML =
    (fall.length ? '<div class="tgroup"><h3>กำลังตก — ระวังซื้อตอนนี้</h3>' +
      trendRows(fall) + '</div>' : '') +
    (rise.length ? '<div class="tgroup"><h3>กำลังมา</h3>' +
      trendRows(rise) + '</div>' : '');
}

// สลับหน้าในพาเนล — ปุ่มช่วงเวลาใช้กับกราฟเท่านั้น จึงซ่อนตอนอยู่หน้าแนวโน้ม
function setPanelPage(which) {
  const isChart = which === 'chart';
  document.getElementById('tChart').setAttribute('aria-pressed', String(isChart));
  document.getElementById('tTrend').setAttribute('aria-pressed', String(!isChart));
  document.getElementById('pageChart').hidden = !isChart;
  document.getElementById('pageTrend').hidden = isChart;
  document.getElementById('cranges').style.visibility = isChart ? '' : 'hidden';
  if (!isChart) drawTrend();
}
document.getElementById('tChart').addEventListener('click', () => setPanelPage('chart'));
document.getElementById('tTrend').addEventListener('click', () => setPanelPage('trend'));

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


def _copy_fonts(out_path: Path) -> None:
    """วางฟอนต์ไว้ข้าง ๆ ไฟล์ HTML — CSS อ้างด้วย path สัมพัทธ์ `fonts/...`

    ต้องคัดลอกทุกครั้งเพราะ build เขียนได้ทั้ง out/dashboard.html (ดูในเครื่อง)
    และ docs/index.html (ที่ deploy) ทั้งสองที่ต้องมี fonts/ ของตัวเอง
    ต้นฉบับอยู่ที่ assets/fonts/ ที่เดียว
    """
    src = ROOT / "assets" / "fonts"
    if not src.is_dir():
        return
    dst = out_path.parent / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            target = dst / f.name
            # ข้ามถ้าเหมือนเดิม จะได้ไม่ทำให้ git เห็นไฟล์เปลี่ยนทุกรอบ scan
            if target.exists() and target.stat().st_size == f.stat().st_size:
                continue
            target.write_bytes(f.read_bytes())


def build(conn: sqlite3.Connection, out_path: Path) -> dict[str, int]:
    rows = db.latest_snapshot_per_title(conn)
    stocked = db.latest_market(conn, "platform")
    mine = db.latest_market(conn, "mine")
    delta = db.market_delta(conn, "platform")

    items: list[Assessment] = []
    for row in rows:
        hist = [c for _, c in db.ccu_history(conn, row["appid"])]
        items.append(assess(conn, row, hist, stocked, mine, delta))

    # แนวโน้มรายวัน คิดทีเดียวทั้งชุด — คนละเรื่องกับ Surge ในคะแนน (ดู trend.py)
    decay = trend.decay_all(db.ccu_by_appid(conn))
    velocity = trend.velocity_all(db.review_series(conn))

    payload = []
    for row, a in zip(rows, items):
        d = asdict(a)
        d["is_free"] = bool(row["is_free"])
        d["history"] = a.history[-20:]
        # จุดข้อมูลพร้อมเวลา สำหรับกราฟเส้น — เก็บเฉพาะเกมที่มี CCU จริง
        # 130 จุด = ประมาณ 30 วันที่ 4 รอบ/วัน เพราะปุ่มช่วงบนกราฟมีถึง 30d
        # ถ้าสแกนถี่ขึ้นหรือเก็บนานขึ้นมาก ไฟล์ HTML จะเริ่มบวม ต้องกลับมาดูตรงนี้
        d["series"] = (
            [[t, c] for t, c in db.ccu_series(conn, a.appid, limit=130)]
            if a.ccu is not None
            else []
        )
        dec = decay.get(a.appid)
        d["decay"] = (
            {"pct": round(dec.pct, 4), "per_day": round(dec.per_day, 4),
             "days": dec.days, "hour": dec.hour,
             "points": [[t, c] for t, c in dec.points]}
            if dec else None
        )
        d["rev_per_day"] = round(velocity[a.appid], 1) if a.appid in velocity else None
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
    _copy_fonts(out_path)
    return meta
