# Game Radar

จับเกม Steam ที่กำลังพุ่ง แล้วคัดเฉพาะตัวที่เอาไปปล่อยเช่าไอดีได้ ออกมาเป็นหน้า dashboard

**หน้า dashboard สด:** https://dolopert.github.io/TrendGame/

คำศัพท์ที่ใช้ทั้งโปรเจกต์อยู่ที่ [CONTEXT.md](./CONTEXT.md) — อ่านก่อนแก้โค้ด

## ใช้ยังไง

รันวันละครั้ง (เก็บข้อมูล + สร้าง dashboard ในคำสั่งเดียว):

```bash
uv run --project game-radar game-radar run
```

แยกเป็นขั้น ๆ ถ้าต้องการ:

```bash
uv run --project game-radar game-radar scan
```

```bash
uv run --project game-radar game-radar dash
```

ดูอันดับเร็ว ๆ ในเทอร์มินัลโดยไม่ต้องเปิดเบราว์เซอร์:

```bash
uv run --project game-radar game-radar top -n 15
```

เปิด dashboard: ใช้ preview config ชื่อ `game-radar` (พอร์ต 5501) หรือเปิดไฟล์
`out/dashboard.html` ตรง ๆ ก็ได้

### อัปเดตหน้าเว็บที่ deploy ไว้

หน้าที่ https://dolopert.github.io/TrendGame/ มาจาก `docs/index.html` ซึ่ง commit ไว้ในรีโป
(GitHub Pages ชี้มาที่โฟลเดอร์ `docs/` ของ branch `main`) อัปเดตด้วยการสร้างทับแล้วพุช:

```bash
uv run --project game-radar game-radar scan
```

```bash
uv run --project game-radar game-radar dash --out game-radar/docs/index.html
```

ข้อควรรู้: `docs/index.html` เป็นไฟล์ที่ **สร้างขึ้นมา** ไม่ใช่ไฟล์ที่แก้ด้วยมือ
แก้หน้าตาให้ไปแก้ template ใน `src/game_radar/render.py` แทน

## ข้อมูลมาจากไหน

ทุก endpoint เป็นของฟรี ไม่ต้องใช้ API key และไม่มีอะไรต้องใส่ `.env`

| endpoint | ได้อะไร | ยิงกี่ครั้งต่อรอบ |
|---|---|---|
| `ISteamChartsService/GetMostPlayedGames` | 100 อันดับ + **อันดับสัปดาห์ก่อน** | 1 |
| `ISteamChartsService/GetGamesByConcurrentPlayers` | CCU สด 100 เกม | 1 |
| `store/api/featuredcategories` | ลดราคา / เกมใหม่ / ขายดี / กำลังมา | 1 |
| `ISteamUserStats/GetNumberOfCurrentPlayers` | CCU รายตัว (เฉพาะเกมนอกชาร์ต) | ~60 |
| `store/api/appdetails` | ราคา หมวดหมู่ แนว ปก วันวางขาย | เท่าจำนวนเกมที่ metadata เก่า |

`appdetails` ถูก Steam จำกัดราว 200 ครั้งต่อ 5 นาที โค้ดจึงหน่วง 1.5 วินาทีต่อครั้ง
และแคชผลไว้ 3 วัน (ตั้งใหม่ได้ที่ `db.stale_appids`) รอบแรกจึงกินเวลาราว 4 นาที
รอบถัด ๆ ไปจะเร็วกว่ามาก

## เรื่องที่ต้องเข้าใจก่อนเชื่อตัวเลข

**คะแนนกระแสมีสองเกรด** และ dashboard บอกไว้ตรงการ์ดทุกใบ:

- ช่วง 3 วันแรกยังไม่มีประวัติของตัวเอง คะแนนจึงมาจาก `last_week_rank`
  ที่ Steam แถมมากับชาร์ต — หยาบกว่า แต่มีให้ใช้ตั้งแต่วันแรกเลยไม่ต้องรอ
- ตั้งแต่รอบที่ 4 เป็นต้นไป ระบบสลับไปเทียบกับค่ากลางของตัวเกมเองอัตโนมัติ ซึ่งแม่นกว่ามาก

**"เข้าชาร์ตใหม่" ดูจากอันดับสัปดาห์ก่อนที่เกิน 100** ไม่ใช่จากการที่ไม่มีอันดับ
— ตอนแรกเข้าใจว่า Steam จะไม่ส่ง `last_week_rank` มาให้เกมที่สัปดาห์ก่อนยังไม่ติดชาร์ต
แต่พอยิงจริงพบว่ามันส่งมาเสมอ และส่งค่าที่เกิน 100 ได้ด้วย (เจอ 152 มาแล้ว)
เกมที่กระโดดจากนอกชาร์ตเข้ามาติด 100 อันดับคือสิ่งที่โปรเจกต์นี้ตั้งใจจะจับ

**โหมดผู้เล่นไม่ใช่ตัวตัดสิทธิ์** ตอนแรกออกแบบไว้ว่าจะคัดเกมที่มี Multi-player ทิ้ง
แต่พอเอา How to Fish (`appid 4001890`) มาตรวจจริง พบว่ามันมีทั้ง Single-player,
Multi-player, Co-op และ Online Co-op ครบ — เกณฑ์นั้นจะคัดเกมตัวอย่างที่เป็นต้นเรื่องทิ้งเอง
ตอนนี้โหมดผู้เล่นจึงเป็นแค่ป้ายกำกับกับตัวกรองที่คนกดเอง

## ความเสี่ยงของโมเดลธุรกิจ

Steam Subscriber Agreement ไม่อนุญาตให้แชร์หรือให้เช่าบัญชี ไอดีถูกล็อกได้ถ้ามีคนรายงาน
เกมที่มี Online PvP เสี่ยงเพิ่มเพราะระบบ anti-cheat จับ IP ที่กระโดดไปมา
— dashboard ติดหมายเหตุนี้ไว้ที่การ์ดของเกมกลุ่มนั้นแล้ว ส่วนจะรับความเสี่ยงแค่ไหนเป็นการตัดสินใจของคุณ

## โครงสร้าง

```
src/game_radar/
  steam.py    ตัวห่อ Steam API — ไม่มี logic ธุรกิจ
  db.py       schema + คำสั่งอ่านเขียน SQLite
  scan.py     การเก็บข้อมูลหนึ่งรอบ
  score.py    Surge กับ Prospect (แยกกันคนละฟังก์ชัน)
  render.py   สร้าง dashboard.html
  cli.py      คำสั่ง
data/         ฐานข้อมูล (gitignore)
out/          dashboard ที่สร้างแล้ว (gitignore)
```
