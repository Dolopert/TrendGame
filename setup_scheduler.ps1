# ตั้งให้ Windows เก็บสต็อกตลาดเช่าให้อัตโนมัติทุกวัน แล้วส่งขึ้นรีโป
#
# ทำไมต้องรันจากเครื่องนี้ ไม่ใช่บน GitHub: หน้าร้าน 499k อยู่หลัง Cloudflare
# ที่กัน IP ของ datacenter - เครื่องของ GitHub ได้ HTTP 403 พร้อมหน้า challenge
# ส่วนเน็ตบ้านผ่านปกติ จึงแบ่งหน้าที่กัน cloud เก็บ Steam / เครื่องนี้เก็บตลาด
#
# ทำไมต้องอัตโนมัติ: ตารางสต็อกตลาดมีค่าที่ "ความต่อเนื่อง" ไม่ใช่ความละเอียด
# ขาดไปวันหนึ่งคือเสียจุดเปรียบเทียบวันนั้นไปถาวร ย้อนกลับไปเก็บไม่ได้
#
# เวลาเริ่มต้น 21:00 ตั้งใจให้ห่างจาก workflow บน cloud (09:00) ครึ่งวัน
# ทั้งสองฝั่งเขียน data/radar.sql เหมือนกัน ยิ่งห่างยิ่งชนกันยาก
#
# หมายเหตุสำหรับคนที่จะมาแก้ไฟล์นี้:
#   - ไฟล์ต้องเป็น UTF-8 พร้อม BOM ไม่งั้น PowerShell 5.1 อ่านภาษาไทยเป็น cp874 แล้ว parser พัง
#   - อย่าใช้ backtick ขึ้นบรรทัดใหม่ ถ้าไฟล์เป็น CRLF หรือมีช่องว่างตามหลัง backtick
#     การต่อบรรทัดจะพังเงียบ ๆ ใช้ splatting (@{...}) แทนซึ่งไม่มีปัญหานี้
#
# รันไฟล์นี้ครั้งเดียว:  powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
# ถอนออก:               powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1 -Remove

param(
    [switch]$Remove,
    [string]$Time = "21:00"
)

$TaskName = "GameRadar-Market"
$Project  = "C:\Users\diffy\Desktop\Claudex\game-radar"
$Script   = Join-Path $Project "update_market.ps1"

function Unregister-IfExists {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) { $t | Unregister-ScheduledTask -Confirm:$false }
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-IfExists
        "ถอน task '$TaskName' ออกแล้ว"
    } else {
        "ไม่พบ task '$TaskName' อยู่แล้ว"
    }
    return
}

if (-not (Test-Path $Script)) { throw "ไม่พบสคริปต์ $Script" }

$actionArgs = @{
    Execute          = "powershell.exe"
    Argument         = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
    WorkingDirectory = $Project
}
$action = New-ScheduledTaskAction @actionArgs

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# StartWhenAvailable สำคัญ: ถ้าวันไหนเครื่องปิดตอนถึงเวลา ให้ไปรันทันทีที่เปิด
# ไม่งั้นวันที่ปิดเครื่องจะกลายเป็นรูในข้อมูลถาวร
# WakeToRun ปลุกเครื่องจาก sleep/hibernate มารันตามเวลา
# ปลุกจากเครื่องที่ปิดสนิท (shutdown) ไม่ได้ — อันนั้นไม่มีอะไรทำได้
# และต้องให้ power plan ของ Windows อนุญาต wake timer ด้วย
# เช็คด้วย: powercfg /q SCHEME_CURRENT SUB_SLEEP ALLOWWAKETIMERS
$settingsArgs = @{
    StartWhenAvailable         = $true
    WakeToRun                  = $true
    DontStopIfGoingOnBatteries = $true
    AllowStartIfOnBatteries    = $true
    ExecutionTimeLimit         = (New-TimeSpan -Minutes 15)
}
$settings = New-ScheduledTaskSettingsSet @settingsArgs

Unregister-IfExists

# ต้องระบุ -TaskPath "\" และใช้ description เป็น ASCII
# ไม่งั้น PowerShell 5.1 บนเครื่อง codepage ไทยจะสร้างโฟลเดอร์ชื่ออ่านไม่ออก
# แล้ว Start-ScheduledTask กับ Get-ScheduledTaskInfo จะหา task ไม่เจอ
$registerArgs = @{
    TaskName    = $TaskName
    TaskPath    = "\"
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = "Game Radar - daily rental market snapshot + push"
}
Register-ScheduledTask @registerArgs | Out-Null

"ตั้ง task '$TaskName' แล้ว - รันทุกวันเวลา $Time"
"  สั่งรัน: $Script"
"  เปลี่ยนเวลา: setup_scheduler.ps1 -Time 08:00"
"  ถอนออก:     setup_scheduler.ps1 -Remove"
