# ตั้งให้ Windows เก็บสต็อกตลาดเช่าให้อัตโนมัติทุกวัน
#
# ทำไมต้องอัตโนมัติ: ตารางสต็อกตลาดมีค่าที่ "ความต่อเนื่อง" ไม่ใช่ความละเอียด
# ขาดไปวันหนึ่งคือเสียจุดเปรียบเทียบวันนั้นไปถาวร ย้อนกลับไปเก็บไม่ได้
#
# รันไฟล์นี้ครั้งเดียว:  powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
# ถอนออก:               powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1 -Remove

param(
    [switch]$Remove,
    [string]$Time = "09:00"
)

$TaskName = "GameRadar-Market"
$Uv       = "C:\Users\diffy\.local\bin\uv.exe"
$Project  = "C:\Users\diffy\Desktop\Claudex\game-radar"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Get-ScheduledTask -TaskName $TaskName | Unregister-ScheduledTask -Confirm:$false
        "ถอน task '$TaskName' ออกแล้ว"
    } else {
        "ไม่พบ task '$TaskName' อยู่แล้ว"
    }
    return
}

if (-not (Test-Path $Uv))     { throw "ไม่พบ uv ที่ $Uv" }
if (-not (Test-Path $Project)) { throw "ไม่พบโปรเจกต์ที่ $Project" }

$action = New-ScheduledTaskAction -Execute $Uv `
    -Argument "run --project `"$Project`" game-radar market" `
    -WorkingDirectory $Project

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# StartWhenAvailable สำคัญมาก: ถ้าวันไหนเครื่องปิดตอนถึงเวลา ให้ไปรันทันทีที่เปิด
# ไม่งั้นวันที่ปิดเครื่องจะกลายเป็นรูในข้อมูลถาวร
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Get-ScheduledTask -TaskName $TaskName | Unregister-ScheduledTask -Confirm:$false
}

# หมายเหตุ: ต้องระบุ -TaskPath "\" และใช้ description เป็น ASCII
# PowerShell 5.1 บนเครื่องที่ codepage เป็นไทย จะเอาข้อความไทยไปสร้างเป็นชื่อโฟลเดอร์
# ที่อ่านไม่ออก แล้ว Start-ScheduledTask กับ Get-ScheduledTaskInfo จะหา task ไม่เจอ
Register-ScheduledTask -TaskName $TaskName -TaskPath "\" -Action $action `
    -Trigger $trigger -Settings $settings `
    -Description "Game Radar - daily rental market snapshot" | Out-Null

"ตั้ง task '$TaskName' แล้ว - รันทุกวันเวลา $Time"
"  เปลี่ยนเวลา: setup_scheduler.ps1 -Time 21:00"
"  ถอนออก:     setup_scheduler.ps1 -Remove"
