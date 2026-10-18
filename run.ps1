# 启动 GUI-of-Edge-TTS（不打包、不跑门禁，只启动）。
#
# 双击本文件即可；也可以在 PowerShell 里：
#     powershell -ExecutionPolicy Bypass -File run.ps1
#
# 可选参数（直接传给程序）：
#     -Arguments "--settings"        启动后直接打开设置窗口
#     -Arguments "--version"         打印版本后退出（不创建窗口）
#     -Arguments "--selftest"        不创建窗口地跑一遍自检
#     -Arguments "--smoke"           跑一次真实生成（联网）并退出
#     -Arguments "--out D:\某个目录" 预设输出目录
#
# ⚠️ 想看那些命令的**文字输出**时，请用 cmd 重定向，例如：
#     cmd /c "run.cmd --selftest > out.txt 2>&1"
#   原因：PowerShell 对"图形界面程序"不等待、也不把它的输出接到管道上，
#   所以 `run.ps1 --selftest > out.txt` 会得到一个空文件——**这不是程序的
#   bug**，是打包成 windowed（双击不弹黑框）时的代价；源码运行时输出正常。
#   经 run.cmd 调用，或直接在 cmd 里调用，输出都正常。

[CmdletBinding()]
param(
    [string]$Arguments = ""
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot

# 从源码跑（开发态）。打包产物由 `build.ps1` 生成到 dist/，不在这里判断：
# 本地没有 dist/ 时不必先打印一句"没找到 exe"再回退，直接启动即可。
function Find-Python {
    $candidates = @(
        (Join-Path $repo "edge-tts-env\python.exe"),
        "D:\Coding\GUI-of-Edge-TTS\etts-dev\python.exe",
        "D:\Coding\GUI-of-Edge-TTS\edge-tts-env\python.exe",
        (Join-Path $env:USERPROFILE "miniconda3\envs\edge-tts-env\python.exe"),
        (Join-Path $env:USERPROFILE "miniconda3\python.exe")
    )
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { $candidates += $found.Source }
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path $candidate)) { continue }
        & $candidate -c "import edge_tts, tkinter" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "找不到可用的 Python（需要装了 edge-tts 与 tkinter 的解释器）。" -ForegroundColor Red
    Read-Host "按回车关闭"
    exit 1
}

$entry = Join-Path $repo "src\GUI-of-Edge-TTS.py"
Write-Host "从源码启动：$python $entry"
if ($Arguments) {
    & $python -X utf8 $entry @($Arguments.Split(" "))
} else {
    & $python -X utf8 $entry
}
exit $LASTEXITCODE
