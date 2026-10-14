# เก็บข้อมูลตลาดเช่าจากเครื่องนี้ แล้วส่งขึ้นรีโป
#
# ทำไมต้องรันจากเครื่องบ้าน: หน้าร้าน 499k อยู่หลัง Cloudflare ที่กัน IP ของ
# datacenter — เครื่องของ GitHub ได้ HTTP 403 พร้อมหน้า challenge ส่วนเน็ตบ้านผ่านปกติ
# เครื่องนี้จึงเป็นที่เดียวที่เก็บฝั่งตลาดได้
#
# ส่วนฝั่ง Steam เก็บที่นี่ด้วยในฐานะ "ตัวสำรอง" ของงานบน GitHub Actions
# เหตุผล: cron ของ GitHub ไม่รันตามตารางจริง — ถาม API แล้วพบว่า workflow
# "เก็บข้อมูล Steam" รันมา 2 ครั้ง เป็น workflow_dispatch (กดเอง) ทั้งคู่
# ส่วน schedule = 0 ครั้ง ทำให้ข้อมูล Steam ค้างไป 18 ชม. โดยไม่มีใครรู้
# ตัว Task Scheduler ของเครื่องนี้รันตรงเวลาทุกครั้ง จึงเชื่อถือได้กว่า
# ถ้า cloud รันได้จริงเมื่อไหร่ ข้อมูลจะซ้อนกันเฉย ๆ ไม่เสียหาย
# (snapshot มี unique index ที่ appid+taken_at และคนละรอบก็คนละเวลาอยู่แล้ว)
#
# ลำดับข้างล่างสำคัญมาก ห้ามสลับ:
#   pull -> restore --force -> market -> scan -> dash -> dump -> commit -> push
# ขั้น restore --force คือหัวใจ เพราะต้องเอาข้อมูลที่ cloud เก็บไว้มาเป็นฐานก่อน
# ถ้าข้ามไป ตอน dump จะเขียนทับด้วยฐานข้อมูลเก่าในเครื่อง แล้วข้อมูลของ cloud หายทันที

# -TestFunctionsOnly: โหลดแค่ตัวแปร+ฟังก์ชันแล้วหยุด (ใช้โดย tools/test_update_market_git.ps1 เท่านั้น)
param(
    [switch]$NoPush,
    [string]$Project = "C:\Users\diffy\Desktop\Claudex\game-radar",
    [switch]$TestFunctionsOnly
)

$ErrorActionPreference = "Stop"
$Uv      = "C:\Users\diffy\.local\bin\uv.exe"
$Log     = Join-Path $Project "update_market.log"

function Say($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    $line
    Add-Content -Path $Log -Value $line -Encoding utf8
}

# บรรทัดท้ายจาก git จริง (ตัด hint: ออก) — ให้ log/error บอกสาเหตุจริง ไม่ต้องเดา
# (เคส 7–14 ต.ค. 69: push ล้มด้วย non-fast-forward แต่ข้อความเดิมบอกให้ไป login git)
function Get-GitTail($out) {
    $lines = @($out | ForEach-Object { "$_" } | Where-Object { $_ -and $_ -notmatch '^hint:' })
    ($lines | Select-Object -Last 2) -join " | "
}

# ทุกฟังก์ชัน git ข้างล่างตั้ง ErrorActionPreference = Continue เฉพาะในฟังก์ชัน:
# PS 5.1 แปลง stderr ของ git (2>&1) เป็น ErrorRecord — ถ้าเป็น Stop จะ throw ทั้งที่ git
# สำเร็จ (git เขียน progress ลง stderr ตลอด) จึงเช็ค $LASTEXITCODE เองทุกจุดแทน

# เศษสถานะจากรอบที่ถูกตัดกลางทาง (rebase ค้าง / HEAD detached) ต้องเคลียร์ก่อน sync
# ไม่งั้นรอบต่อ ๆ ไปจะล้มต่อกันหรือ commit ลง HEAD ลอย ๆ ที่ไม่มี branch ไหนถือ
function Repair-LeftoverState {
    $ErrorActionPreference = "Continue"
    $gitDir = Join-Path $Project ".git"
    if ((Test-Path (Join-Path $gitDir "rebase-merge")) -or (Test-Path (Join-Path $gitDir "rebase-apply"))) {
        Say "พบ rebase ค้างจากรอบก่อน — rebase --abort กลับสถานะเดิม"
        $out = git rebase --abort 2>&1
        if ($LASTEXITCODE -ne 0) { throw "rebase --abort ไม่สำเร็จ: $(Get-GitTail $out)" }
    }
    git symbolic-ref --short -q HEAD 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # เก็บ sha ไว้ใน branch สำรองก่อนออก — commit บน HEAD ลอยจะได้ไม่กลายเป็น dangling
        $sha    = "$(git rev-parse HEAD)".Trim()
        $backup = "backup/detached-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        $out = git branch $backup $sha 2>&1
        if ($LASTEXITCODE -ne 0) { throw "สร้าง $backup ไม่สำเร็จ: $(Get-GitTail $out)" }
        Say "HEAD detached ค้างที่ $sha — เก็บไว้ที่ $backup แล้วกลับ main"
        $out = git checkout main 2>&1
        if ($LASTEXITCODE -ne 0) { throw "checkout main ไม่สำเร็จ: $(Get-GitTail $out)" }
    }
}

# ดึงของใหม่จาก origin/main ด้วย merge (เลิกใช้ pull --rebase)
# ทำไม: rebase เขียน commit ท้องถิ่นใหม่ทีละตัว — เคส 7–14 ต.ค. 69 ทางสำรองหลัง rebase
# ย้าย main ไป chain ที่ replay ไม่ครบ ข้อมูลตลาดหายหลายวัน ส่วน merge ไม่แตะ commit เดิม
# และ main ขยับเฉพาะตอน commit สำเร็จ → ล้มเมื่อไหร่ merge --abort ก็กลับ main เดิมครบ
# ห้ามแตะ branch ref ตรง ๆ ในฟังก์ชันนี้ (ไม่ย้าย ref เอง ไม่ checkout)
function Invoke-Sync {
    $ErrorActionPreference = "Continue"
    # ไม่นับไฟล์ untracked (เช่น log) — มันไม่ขวาง merge และ stash ปกติก็ไม่เก็บอยู่แล้ว
    if (git status --porcelain --untracked-files=no) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $out = git stash push -m "ps1 autostash $stamp" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "git stash ไม่สำเร็จ: $(Get-GitTail $out)" }
        # ไม่ pop เอง — ของที่ค้างมักเป็นไฟล์ generate ที่จะชนซ้ำ ให้คนดูด้วย git stash list
        Say "worktree มีของค้าง — stash ไว้ (ps1 autostash $stamp) ไม่ pop อัตโนมัติ"
    }

    $out = git fetch origin main 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git fetch ล้มเหลว: $(Get-GitTail $out)" }

    $behind = [int]"$(git rev-list --count HEAD..origin/main)"
    if ($behind -eq 0) { return }

    $out = git merge --no-edit origin/main 2>&1
    if ($LASTEXITCODE -eq 0) {
        Say "รวม origin/main แล้ว ($behind commit ใหม่)"
        return
    }
    if (-not (git ls-files -u)) { throw "git merge ล้มเหลว (ไม่ใช่ conflict): $(Get-GitTail $out)" }

    # ไฟล์ที่ generate ใหม่ทุกวัน (data/radar.sql, docs/index.html) ชนกันได้ทุกครั้งที่ cloud
    # push ข้อมูลระหว่างทาง — เคยทำ pipeline ตาย 3 วัน (21–23 ก.ย. 69) เพราะ throw ทิ้งทั้งรอบ
    # → รวมข้อมูลสองฝั่งที่ระดับ SQLite (ไม่ทิ้งฝั่งไหน) แล้วไปต่อ
    # เครื่องมือตัวนี้อยู่ใน commit ท้องถิ่น แต่ตอน rebase git จะ checkout ต้นทาง
    # ทับ worktree → tools/ หายทั้งโฟลเดอร์ ทำให้เรียกไม่เจอ (เกิดจริง 23 ก.ย. 69
    # รอบ 22:00 ได้ exit 2 แล้วทิ้ง rebase ค้าง) จึงถอยไปดึงสำเนาจาก ref ท้องถิ่น
    # "main" มารันชั่วคราว (สำเนานอกรีโปทำงานได้ เพราะเครื่องมือหาราก repo จาก cwd)
    $toolRel  = "tools/merge_radar_sql.py"
    $toolPath = Join-Path $Project $toolRel
    if (-not (Test-Path $toolPath)) {
        $toolPath = Join-Path $env:TEMP "game-radar-tools\merge_radar_sql.py"
        New-Item -ItemType Directory -Force -Path (Split-Path $toolPath) | Out-Null
        cmd /c "git cat-file blob main:$toolRel > `"$toolPath`""
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $toolPath)) {
            git merge --abort 2>&1 | Out-Null
            throw "ไม่พบ $toolRel ทั้งใน worktree และใน ref main — merge --abort แล้ว ต้องแก้ conflict ด้วยมือ"
        }
        Say "ไม่พบเครื่องมือใน worktree — ใช้สำเนาจาก ref main แทน"
    }
    Say "merge ชนกัน — รวมข้อมูลที่ระดับ DB ($toolRel)"
    & $Uv run python $toolPath
    if ($LASTEXITCODE -ne 0) {
        $code = $LASTEXITCODE
        git merge --abort 2>&1 | Out-Null
        throw "merge_radar_sql.py ล้มเหลว (exit $code) — merge --abort กลับ main เดิมแล้ว"
    }

    git add data/radar.sql docs/index.html 2>&1 | Out-Null
    $out = git commit --no-edit 2>&1
    if ($LASTEXITCODE -ne 0) {
        git merge --abort 2>&1 | Out-Null
        throw "commit หลัง merge ไม่สำเร็จ — merge --abort กลับ main เดิมแล้ว: $(Get-GitTail $out)"
    }
    Say "รวมข้อมูลเสร็จ — ไปต่อ"
}

# push ล้มส่วนใหญ่เพราะ cloud push แทรกระหว่าง sync→push (non-fast-forward)
# → ดึงของใหม่มารวมแล้วลองซ้ำ แทนที่จะ throw ทิ้งทั้งรอบ
function Invoke-PushWithRetry {
    $ErrorActionPreference = "Continue"
    $max = 3
    for ($i = 1; $i -le $max; $i++) {
        # GCM หา entry ที่เก็บไว้ไม่เจอถ้าไม่ระบุ username (เจอจริง 24 ก.ย. 69: push ล้มด้วย
        # "Cannot prompt / unable to get password" ทั้งที่ credential อยู่ใน Credential Manager)
        $out = git -c credential.interactive=false -c credential.username=Dolopert push origin main 2>&1
        if ($LASTEXITCODE -eq 0) { return }
        $tail = Get-GitTail $out
        Say "push รอบ $i/$max ไม่ผ่าน — git: $tail"
        if ($i -eq $max) { break }
        Say "ดึงของใหม่ (fetch+merge) แล้วลอง push ซ้ำ"
        Invoke-Sync
    }
    throw "push ไม่สำเร็จครบ $max รอบ — git: $tail"
}

if ($TestFunctionsOnly) { return }

try {
    Set-Location $Project
    $env:PYTHONIOENCODING = "utf-8"
    # งานนี้รันแบบไม่มีหน้าจอ (Task Scheduler + -WindowStyle Hidden) — ถ้า git ต้องถาม
    # credential มันจะค้างจน Task ถูกตัดที่ ExecutionTimeLimit (เคสจริง 20 ก.ย. 69:
    # "push ขึ้นรีโป" แล้วเงียบไป = ถูกตัดกลาง push) → ปิด prompt ให้ล้มเร็วแล้วจบรอบ
    # credential ที่เก็บไว้แล้วยังใช้ได้ปกติ (ตัวนี้ห้ามเฉพาะการ *ถาม*)
    $env:GIT_TERMINAL_PROMPT = "0"
    $env:GCM_INTERACTIVE    = "never"
    $env:GIT_EDITOR         = "true"

    Repair-LeftoverState
    Say "pull ข้อมูลล่าสุดจากรีโป"
    Invoke-Sync

    Say "สร้างฐานข้อมูลใหม่จาก data/radar.sql (เอาของ cloud มาเป็นฐาน)"
    & $Uv run game-radar restore --force | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "restore ไม่สำเร็จ" }

    Say "เก็บสต็อกตลาดเช่า"
    & $Uv run game-radar market
    if ($LASTEXITCODE -ne 0) { throw "เก็บข้อมูลตลาดไม่สำเร็จ" }

    # ร้านเรา (หลังบ้าน 499k): สถานะไอดี + ยอด/ประวัติเช่า -> data/own.sqlite3 + out/own.html
    # ต้องใช้ SyncProfile Brave (พอร์ต 9222) ที่ login 499k ค้าง — ถ้า Hermes/เบราว์เซอร์
    # ไม่ได้เปิดอยู่ หรือ session หมดอายุ (ทุก ~3 วัน) จะล้มแบบไม่ fatal แล้วไปต่อ
    # เพราะ radar.sql/docs/index.html ยังต้อง push ตามปกติ (ข้อมูลคนละฐานกับ mine)
    Say "เก็บสถานะ/ยอดร้านเรา (หลังบ้าน 499k)"
    & $Uv run game-radar mine
    if ($LASTEXITCODE -ge 2) {
        Say "เตือน: เก็บข้อมูลร้านเราไม่สำเร็จ (exit $LASTEXITCODE) - ดู out/own.html ครั้งถัดไปหรือ re-login 499k ใน SyncProfile Brave"
    }

    # ไม่ throw ถ้าฝั่ง Steam ล้ม — ข้อมูลตลาดที่เพิ่งเก็บได้ต้องไม่หายไปด้วย
    # เครื่องนี้เป็นที่เดียวที่เก็บฝั่งตลาดได้ ส่วนฝั่ง Steam ยังมี cloud เป็นอีกทาง
    # (แนวเดียวกับ market --allow-fail บน CI)
    Say "เก็บข้อมูล Steam (สำรองของงานบน GitHub Actions)"
    & $Uv run game-radar scan --metadata-limit 400
    if ($LASTEXITCODE -ne 0) {
        Say "เตือน: เก็บข้อมูล Steam ไม่สำเร็จ (exit $LASTEXITCODE) - ไปต่อด้วยข้อมูลตลาดอย่างเดียว"
        $SteamOk = $false
    }
    else {
        $SteamOk = $true
    }

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
    $what  = if ($SteamOk) { "ข้อมูล Steam + ตลาด" } else { "ข้อมูลตลาด" }
    git commit -q -m "$what + หน้าเว็บ $stamp (จากเครื่องบ้าน)"
    if ($LASTEXITCODE -ne 0) { throw "commit ไม่สำเร็จ" }

    if ($NoPush) {
        Say "commit แล้ว ยังไม่ push ตามที่สั่ง (-NoPush)"
        exit 0
    }

    Say "push ขึ้นรีโป"
    Invoke-PushWithRetry

    Say "เสร็จเรียบร้อย"
    exit 0
}
catch {
    Say "ล้มเหลว: $_"
    exit 1
}
