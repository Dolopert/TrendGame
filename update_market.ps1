# เก็บข้อมูลตลาดเช่าจากเครื่องนี้ แล้วส่งขึ้นรีโป
#
# ทำไมต้องรันจากเครื่องบ้าน: หน้าร้าน 499k อยู่หลัง Cloudflare ที่กัน IP ของ
# datacenter — เครื่องของ GitHub ได้ HTTP 403 พร้อมหน้า challenge ส่วนเน็ตบ้านผ่านปกติ
# จึงแบ่งหน้าที่: cloud เก็บข้อมูล Steam ทุกวัน / เครื่องนี้เก็บข้อมูลตลาด
#
# ลำดับข้างล่างสำคัญมาก ห้ามสลับ:
#   pull -> restore --force -> market -> dump -> commit -> push
# ขั้น restore --force คือหัวใจ เพราะต้องเอาข้อมูลที่ cloud เก็บไว้มาเป็นฐานก่อน
# ถ้าข้ามไป ตอน dump จะเขียนทับด้วยฐานข้อมูลเก่าในเครื่อง แล้วข้อมูลของ cloud หายทันที

param([switch]$NoPush)

$ErrorActionPreference = "Stop"
$Project = "C:\Users\diffy\Desktop\Claudex\game-radar"
$Uv      = "C:\Users\diffy\.local\bin\uv.exe"
$Log     = Join-Path $Project "update_market.log"

function Say($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line
    Add-Content -Path $Log -Value $line -Encoding utf8
}

try {
    Set-Location $Project
    $env:PYTHONIOENCODING = "utf-8"

    Say "pull ข้อมูลล่าสุดจากรีโป"
    git pull --rebase --autostash origin main | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git pull ไม่สำเร็จ (exit $LASTEXITCODE)" }

    Say "สร้างฐานข้อมูลใหม่จาก data/radar.sql (เอาของ cloud มาเป็นฐาน)"
    & $Uv run game-radar restore --force | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "restore ไม่สำเร็จ" }

    Say "เก็บสต็อกตลาดเช่า"
    & $Uv run game-radar market
    if ($LASTEXITCODE -ne 0) { throw "เก็บข้อมูลตลาดไม่สำเร็จ" }

    # ต้องสร้างหน้าเว็บใหม่ด้วย ไม่ใช่แค่เก็บข้อมูล
    # เดิมสคริปต์นี้ push แต่ data/radar.sql หน้าเว็บเลยค้างอยู่ที่รอบ cloud
    # ทั้งที่ข้อมูลตลาดใหม่เข้ามาแล้ว
    Say "สร้างหน้า dashboard ใหม่"
    & $Uv run game-radar dash --out (Join-Path $Project "docs\index.html")
    if ($LASTEXITCODE -ne 0) { throw "สร้าง dashboard ไม่สำเร็จ" }

    Say "เขียนฐานข้อมูลกลับเป็นไฟล์ข้อความ"
    & $Uv run game-radar dump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "dump ไม่สำเร็จ" }

    git add data/radar.sql docs/index.html | Out-Null
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Say "ข้อมูลไม่เปลี่ยน ไม่ต้อง commit"
        exit 0
    }

    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    git commit -q -m "ข้อมูลตลาด + หน้าเว็บ $stamp (จากเครื่องบ้าน)"
    if ($LASTEXITCODE -ne 0) { throw "commit ไม่สำเร็จ" }

    if ($NoPush) {
        Say "commit แล้ว ยังไม่ push ตามที่สั่ง (-NoPush)"
        exit 0
    }

    Say "push ขึ้นรีโป"
    git push origin main | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "push ไม่สำเร็จ - อาจต้องเข้าไป login git ด้วยมือหนึ่งครั้ง" }

    Say "เสร็จเรียบร้อย"
    exit 0
}
catch {
    Say "ล้มเหลว: $_"
    exit 1
}
