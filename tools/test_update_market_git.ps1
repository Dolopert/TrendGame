# เทสต์เส้นทาง git ของ update_market.ps1 (Repair-LeftoverState / Invoke-Sync / Invoke-PushWithRetry)
#
# self-contained: สร้าง bare remote + clone "home" (เครื่องบ้าน) + clone "cloud" (GitHub Actions)
# ใน %TEMP% เอง ด้วย fixture เล็ก (schema จริง + ไม่กี่สิบแถว) แล้วลบทิ้งตอนจบ
# ไม่แตะ repo จริง/remote จริงเลย — รันซ้ำได้ทั้งใน sandbox และใน repo จริง
# exit 0 เฉพาะเมื่อผ่านทุกฉาก
#
# รัน (ต้องเป็น powershell.exe 5.1 แบบเดียวกับ Task Scheduler):
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\test_update_market_git.ps1 [-UvPath <uv.exe|shim.ps1>]

param([string]$UvPath)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Script   = Join-Path $RepoRoot "update_market.ps1"
$ToolSrc  = Join-Path $RepoRoot "tools\merge_radar_sql.py"
if (-not $UvPath) {
    # sandbox ไม่มี venv ให้ uv run → ใช้ shim ข้าง repo ถ้ามี ไม่งั้นใช้ uv จริง
    $shim = Join-Path (Split-Path -Parent $RepoRoot) "uv_shim.ps1"
    if (Test-Path $shim) { $UvPath = $shim } else { $UvPath = "C:\Users\diffy\.local\bin\uv.exe" }
}
$env:GIT_TERMINAL_PROMPT = "0"
$env:GIT_EDITOR          = "true"
$W = Join-Path $env:TEMP ("umgit_test_" + [guid]::NewGuid().ToString("N").Substring(0, 8))

# schema จริงของ data/radar.sql (คัดจาก dump) — ฝังไว้ให้ harness ไม่พึ่งไฟล์นอก repo
$Schema = @'
CREATE TABLE market_snapshot (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    appid         INTEGER NOT NULL,
    taken_at      TEXT NOT NULL,
    scope         TEXT NOT NULL,
    account_count INTEGER NOT NULL,
    game_name     TEXT
);
CREATE TABLE review_snapshot (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    appid        INTEGER NOT NULL,
    taken_at     TEXT NOT NULL,
    review_total INTEGER,
    review_ratio REAL
);
CREATE TABLE snapshot (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    appid            INTEGER NOT NULL REFERENCES title(appid),
    taken_at         TEXT NOT NULL,
    ccu              INTEGER,
    peak_in_game     INTEGER,
    played_rank      INTEGER,
    last_week_rank   INTEGER,
    ccu_rank         INTEGER,
    in_specials      INTEGER DEFAULT 0,
    in_new_releases  INTEGER DEFAULT 0,
    in_top_sellers   INTEGER DEFAULT 0,
    in_coming_soon   INTEGER DEFAULT 0
, in_coop_topsellers INTEGER DEFAULT 0, in_coop_upcoming INTEGER DEFAULT 0, in_coop_new INTEGER DEFAULT 0, coop_topsellers_rank INTEGER, coop_upcoming_rank INTEGER, coop_new_rank INTEGER);
CREATE TABLE title (
    appid               INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    type                TEXT,
    is_free             INTEGER,
    header_image        TEXT,
    release_date        TEXT,
    coming_soon         INTEGER,
    genres              TEXT,
    category_ids        TEXT,
    is_single           INTEGER,
    is_multi            INTEGER,
    is_coop             INTEGER,
    is_online_pvp       INTEGER,
    has_family_sharing  INTEGER,
    price_final         INTEGER,
    price_currency      TEXT,
    discount_percent    INTEGER,
    metadata_fetched_at TEXT
, metadata_failed_at TEXT, review_total INTEGER, review_positive INTEGER, review_ratio REAL, review_desc TEXT, playtime_median_h REAL, playtime_sample INTEGER, reviews_fetched_at TEXT, reviews_failed_at TEXT);
CREATE INDEX idx_snapshot_appid_time ON snapshot(appid, taken_at);
CREATE UNIQUE INDEX idx_snapshot_unique ON snapshot(appid, taken_at);
CREATE INDEX idx_market_appid_time
    ON market_snapshot(appid, scope, taken_at);
CREATE UNIQUE INDEX idx_market_unique
    ON market_snapshot(appid, taken_at, scope);
CREATE UNIQUE INDEX idx_review_snap_unique
    ON review_snapshot(appid, taken_at);
'@
$Base = 20

# ---------- helpers ----------
# git ที่ throw เมื่อ exit != 0 (Continue: กัน PS 5.1 แปลง stderr ของ git เป็น error)
function G {
    $ErrorActionPreference = "Continue"
    $o = & git @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') -> exit $LASTEXITCODE : $(($o | ForEach-Object { "$_" }) -join ' / ')" }
    $o | ForEach-Object { "$_" }
}
# git ที่คืนแค่ exit code (ใช้กับคำสั่งที่ตั้งใจให้ล้ม / เช็คเงื่อนไข)
function GCode {
    $ErrorActionPreference = "Continue"
    & git @args 2>&1 | Out-Null
    $LASTEXITCODE
}
function Write-Utf8($path, $text) {
    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    [IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}
function New-Rows($tag, $n) {
    for ($i = 1; $i -le $n; $i++) {
        "INSERT INTO market_snapshot(appid,taken_at,scope,account_count,game_name) VALUES($(1000 + $i),'$tag-$i','all',$i,'$tag-$i');"
        "INSERT INTO review_snapshot(appid,taken_at,review_total,review_ratio) VALUES($(1000 + $i),'$tag-$i',$i,0.5);"
    }
}
function Add-Rows($dir, $tag, $n) {
    $p = Join-Path $dir "data\radar.sql"
    $lines = @([IO.File]::ReadAllText($p) -split "`n" | Where-Object { $_ -ne "" -and $_ -ne "COMMIT;" })
    $text = ((@($lines) + @(New-Rows $tag $n) + "COMMIT;") -join "`n") + "`n"
    Write-Utf8 $p $text
}
function Set-Html($dir, $tag) { Write-Utf8 (Join-Path $dir "docs\index.html") "<html><body>$tag</body></html>`n" }
# commit ข้อมูลใหม่ (แถว + หน้าเว็บ) แบบเดียวกับรอบเก็บข้อมูลจริง แล้วคืน sha
function Commit-Data($dir, $tag, $n) {
    Add-Rows $dir $tag $n
    Set-Html $dir $tag
    G -C $dir add -A | Out-Null
    G -C $dir commit -q -m "data $tag" | Out-Null
    "$(G -C $dir rev-parse HEAD)".Trim()
}
function Count-Rows($text, $table) { ([regex]::Matches($text, "(?m)^INSERT INTO `"?$table`"?[ (]")).Count }
function Has-Tag($text, $tag) { $text.Contains("'$tag-") }
function Sql-At($dir, $rev) { (G -C $dir show "${rev}:data/radar.sql") -join "`n" }
function Sha($dir, $rev) { "$(G -C $dir rev-parse $rev)".Trim() }
function Assert($cond, $what) {
    if (-not $cond) { throw "ASSERT FAILED: $what" }
    Write-Host "    ok: $what"
}
function Set-Cfg($d) {
    G -C $d config core.autocrlf false | Out-Null
    G -C $d config user.name "test" | Out-Null
    G -C $d config user.email "test@local" | Out-Null
    G -C $d config commit.gpgsign false | Out-Null
}
# โลกจำลอง: remote.git (bare) + home (repo ที่สคริปต์ดูแล) + cloud (อีกเครื่องที่ push แทรก)
function New-World($name) {
    $root   = Join-Path $W $name
    $remote = Join-Path $root "remote.git"
    $seed   = Join-Path $root "seed"
    G init -q --bare -b main $remote | Out-Null
    G init -q -b main $seed | Out-Null
    Set-Cfg $seed
    $rows = for ($i = 1; $i -le $Base; $i++) {
        "INSERT INTO title(appid,name) VALUES($(1000 + $i),'game $i');"
        "INSERT INTO snapshot(appid,taken_at,ccu) VALUES($(1000 + $i),'base-$i',$i);"
    }
    $sql = ((@("BEGIN TRANSACTION;") + ($Schema -split "`r?`n") + @($rows) + @(New-Rows "base" $Base) + "COMMIT;") -join "`n") + "`n"
    Write-Utf8 (Join-Path $seed "data\radar.sql") $sql
    Set-Html $seed "base"
    Write-Utf8 (Join-Path $seed ".gitignore") "update_market.log`n"
    New-Item -ItemType Directory -Force -Path (Join-Path $seed "tools") | Out-Null
    Copy-Item $ToolSrc (Join-Path $seed "tools\merge_radar_sql.py")
    G -C $seed add -A | Out-Null
    G -C $seed commit -q -m "seed" | Out-Null
    G -C $seed remote add origin $remote | Out-Null
    G -C $seed push -q origin main | Out-Null
    $w = @{ Remote = $remote; Home = (Join-Path $root "home"); Cloud = (Join-Path $root "cloud") }
    foreach ($d in @($w.Home, $w.Cloud)) {
        # ต้องปิด autocrlf ตั้งแต่ตอน clone — ถ้า global เปิดไว้ checkout จะแปลงเป็น CRLF ก่อน Set-Cfg
        G clone -q -c core.autocrlf=false $remote $d | Out-Null
        Set-Cfg $d
    }
    $w
}

$Results = New-Object System.Collections.ArrayList
function Run($name, [scriptblock]$body) {
    Write-Host ""
    Write-Host "=== $name"
    $ok = $true; $msg = ""
    try { & $body | ForEach-Object { Write-Host "    | $_" } }
    catch { $ok = $false; $msg = "$_" }
    finally { Set-Location $env:TEMP }
    if ($ok) { Write-Host "PASS  $name" } else { Write-Host "FAIL  $name -- $msg" }
    [void]$Results.Add([pscustomobject]@{ Name = $name; Ok = $ok })
}
# โหลดฟังก์ชันของสคริปต์จริงเข้า scope ของฉาก (ต้อง dot-source ในฉากเอง ไม่ใช่ใน helper)
# แล้ว: . $Script -TestFunctionsOnly -Project $w.Home ; $Uv = $UvPath ; Set-Location $w.Home

Write-Host "script : $Script"
Write-Host "uv     : $UvPath"
Write-Host "work   : $W"
Write-Host "ps     : $($PSVersionTable.PSVersion)"

try {
    Run "1 remote == local -> no merge, no new commit" {
        $w = New-World "s1"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        $before = Sha $w.Home HEAD
        Invoke-Sync
        Assert ((Sha $w.Home HEAD) -eq $before) "HEAD unchanged ($before)"
        Assert (-not (Test-Path (Join-Path $w.Home ".git\MERGE_HEAD"))) "no merge in progress"
        Assert (-not (G stash list)) "clean worktree -> no stash"
    }

    Run "2 remote ahead by 1 -> fast-forward, trees equal" {
        $w = New-World "s2"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        $c = Commit-Data $w.Cloud "cloud1" 5
        G -C $w.Cloud push -q origin main | Out-Null
        Invoke-Sync
        Assert ((Sha $w.Home HEAD) -eq $c) "HEAD == cloud commit (ff)"
        Assert ((Sha $w.Home "HEAD^{tree}") -eq (Sha $w.Cloud "HEAD^{tree}")) "tree identical to cloud"
        Assert ((G symbolic-ref --short HEAD) -eq "main") "on branch main"
    }

    Run "3 diverged, radar.sql edited both sides -> union merge commit, all rows kept" {
        $w = New-World "s3"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        $h = Commit-Data $w.Home "home1" 7
        $c = Commit-Data $w.Cloud "cloud1" 5
        G -C $w.Cloud push -q origin main | Out-Null
        Invoke-Sync
        $parents = @("$(G rev-list --parents -n 1 HEAD)".Trim() -split " ").Count - 1
        Assert ($parents -eq 2) "HEAD is a merge commit (parents=$parents)"
        $sql = Sql-At $w.Home HEAD
        $m = Count-Rows $sql "market_snapshot"; $r = Count-Rows $sql "review_snapshot"
        Assert ($m -eq $Base + 7 + 5) "market_snapshot rows = $m (expect $($Base + 12))"
        Assert ($r -eq $Base + 7 + 5) "review_snapshot rows = $r (expect $($Base + 12))"
        Assert ((Count-Rows $sql "title") -eq $Base -and (Count-Rows $sql "snapshot") -eq $Base) "title/snapshot rows kept ($Base each)"
        Assert ((Has-Tag $sql "home1") -and (Has-Tag $sql "cloud1")) "rows from both sides present"
        Assert ((GCode merge-base --is-ancestor $h HEAD) -eq 0 -and (GCode merge-base --is-ancestor $c HEAD) -eq 0) "both tips are ancestors of HEAD"
        Assert (-not (G status --porcelain --untracked-files=no)) "worktree clean, nothing unmerged"
        Assert ((G symbolic-ref --short HEAD) -eq "main") "on branch main"
    }

    Run "4 local chain of 3 + conflict -> no local commit dropped" {
        $w = New-World "s4"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        $shas = @(1..3 | ForEach-Object { Commit-Data $w.Home "homeC$_" 3 })
        Commit-Data $w.Cloud "cloudC" 4 | Out-Null
        G -C $w.Cloud push -q origin main | Out-Null
        Invoke-Sync
        foreach ($s in $shas) { Assert ((GCode merge-base --is-ancestor $s HEAD) -eq 0) "local $s is ancestor of HEAD" }
        Assert ((GCode merge-base --is-ancestor origin/main HEAD) -eq 0) "origin/main is ancestor of HEAD"
        $sql = Sql-At $w.Home HEAD
        $m = Count-Rows $sql "market_snapshot"
        Assert ($m -eq $Base + 9 + 4) "market_snapshot rows = $m (expect $($Base + 13))"
        Assert ((Has-Tag $sql "homeC1") -and (Has-Tag $sql "homeC2") -and (Has-Tag $sql "homeC3") -and (Has-Tag $sql "cloudC")) "rows of all 3 local commits + cloud present"
        Assert ((G symbolic-ref --short HEAD) -eq "main") "on branch main (not detached)"
    }

    Run "5 push race (cloud pushes after local commit) -> retry succeeds, remote has both" {
        $w = New-World "s5"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        $h = Commit-Data $w.Home "homeP" 6
        Commit-Data $w.Cloud "cloudP" 4 | Out-Null
        G -C $w.Cloud push -q origin main | Out-Null
        Invoke-PushWithRetry
        Assert ((GCode -C $w.Remote merge-base --is-ancestor $h main) -eq 0) "local commit $h reached remote main"
        Assert ((Sha $w.Remote main) -eq (Sha $w.Home HEAD)) "remote main == local HEAD"
        $sql = Sql-At $w.Remote main
        $m = Count-Rows $sql "market_snapshot"
        Assert ($m -eq $Base + 6 + 4) "remote market_snapshot rows = $m (expect $($Base + 10))"
        Assert ((Has-Tag $sql "homeP") -and (Has-Tag $sql "cloudP")) "remote has rows from both sides"
        $log = [IO.File]::ReadAllText((Join-Path $w.Home "update_market.log"), [Text.Encoding]::UTF8)
        Assert ($log -match "push รอบ 1/3 ไม่ผ่าน — git: .*(rejected|failed to push)") "log shows real git reason for push 1 failure"
        Assert ($log -notmatch "login") "log does not guess 'login'"
    }

    Run "6 leftover state: rebase in progress + detached HEAD with commit" {
        $w = New-World "s6"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        # 6a: rebase ค้าง (ชนกลางทาง) เหมือนรอบที่ถูกตัด
        $h = Commit-Data $w.Home "homeR" 2
        Commit-Data $w.Cloud "cloudR" 2 | Out-Null
        G -C $w.Cloud push -q origin main | Out-Null
        G fetch -q origin | Out-Null
        Assert ((GCode rebase origin/main) -ne 0) "setup: rebase stopped on conflict"
        Assert (Test-Path (Join-Path $w.Home ".git\rebase-merge")) "setup: .git/rebase-merge exists"
        Repair-LeftoverState
        Assert (-not (Test-Path (Join-Path $w.Home ".git\rebase-merge"))) "rebase aborted"
        Assert ((G symbolic-ref --short HEAD) -eq "main") "back on main"
        Assert ((Sha $w.Home HEAD) -eq $h) "main still at local commit $h"
        # 6b: HEAD detached + commit ค้าง
        G checkout -q --detach | Out-Null
        $d = Commit-Data $w.Home "detached1" 2
        Assert ((GCode symbolic-ref -q HEAD) -ne 0) "setup: HEAD detached at $d"
        Repair-LeftoverState
        $b = @(G branch --list "backup/detached-*" | ForEach-Object { $_.Trim() })
        Assert ($b.Count -eq 1) "backup branch created ($($b -join ','))"
        Assert ((Sha $w.Home $b[0]) -eq $d) "backup branch points to detached commit"
        Assert ((G symbolic-ref --short HEAD) -eq "main") "back on main"
        Assert ((Sha $w.Home HEAD) -eq $h) "main unchanged"
        Assert ((GCode cat-file -e "$d^{commit}") -eq 0) "detached sha still reachable"
    }

    Run "7 dirty worktree before sync -> stash created, sync continues" {
        $w = New-World "s7"
        . $Script -TestFunctionsOnly -Project $w.Home; $Uv = $UvPath; Set-Location $w.Home
        $c = Commit-Data $w.Cloud "cloudD" 3
        G -C $w.Cloud push -q origin main | Out-Null
        Set-Html $w.Home "dirty-local"
        Assert ([bool](G status --porcelain --untracked-files=no)) "setup: worktree dirty"
        Invoke-Sync
        Assert ((G stash list) -match "ps1 autostash") "stash 'ps1 autostash' created"
        Assert ((Sha $w.Home HEAD) -eq $c) "synced to cloud commit"
        Assert (-not (G status --porcelain --untracked-files=no)) "worktree clean after sync"
    }

    Run "8 file checks: syntax (PS 5.1 parser) + BOM + no 'branch -f'" {
        $e = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$null, [ref]$e)
        Assert (-not $e) "syntax OK"
        $bytes = [IO.File]::ReadAllBytes($Script)
        Assert ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) "UTF-8 BOM present"
        Assert (-not (Select-String -Path $Script -SimpleMatch "branch -f")) "no 'branch -f' in file"
    }
}
finally {
    Set-Location $env:TEMP
    if (Test-Path $W) { Remove-Item -Recurse -Force $W }
}

$pass = @($Results | Where-Object { $_.Ok }).Count
Write-Host ""
Write-Host "RESULT: $pass/$($Results.Count) passed"
if ($pass -eq $Results.Count -and $Results.Count -eq 8) { exit 0 } else { exit 1 }
