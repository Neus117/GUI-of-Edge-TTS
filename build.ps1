# 打包一个可发布的 exe，并把"它自报的版本"核对一遍。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File build.ps1
#   powershell -ExecutionPolicy Bypass -File build.ps1 -SkipGates   # 只打包（调试用）
#
# 顺序不能换：先跑门禁，再注入提交哈希，再打包，最后**运行产物核对版本**。
# 「我以为我写进去了」和「它真的在里面」是两件事（归档 02 第 26.1 节）。
#
# 注意：这个文件**必须带 UTF-8 BOM**。Windows PowerShell 5.1 读没有 BOM 的
# UTF-8 会按 GBK 解码，中文变乱码、字符串缺少终止符。tools/add_bom.py 守这条。
# 另外：这里**不内联 Python 代码**（两层转义踩过坑，见归档 01 错误八），
# 逻辑都在 tools/build_info.py 里。

[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SkipGates
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

# ---- 1. 找有 edge-tts 的解释器 -------------------------------------------
$candidates = @()
if ($Python) { $candidates += $Python }
$candidates += (Join-Path $repo "etts-dev\python.exe")
$candidates += (Join-Path $repo "edge-tts-env\python.exe")
$candidates += (Join-Path $env:USERPROFILE "miniconda3\envs\edge-tts-env\python.exe")
$candidates += (Join-Path $env:USERPROFILE "miniconda3\python.exe")
$command = Get-Command python -ErrorAction SilentlyContinue
if ($command) { $candidates += $command.Source }

$python = $null
foreach ($candidate in $candidates) {
    if (-not $candidate -or -not (Test-Path $candidate)) { continue }
    $probe = & $candidate -c "import edge_tts, tkinter, PyInstaller; print(edge_tts.__version__)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $probe) {
        $python = $candidate
        Write-Host "解释器：$candidate（edge-tts $probe）"
        break
    }
}
if (-not $python) {
    throw "找不到同时装了 edge-tts、tkinter、PyInstaller 的 Python。用 -Python <路径> 指定。"
}

$buildInfo = Join-Path $repo "tools\build_info.py"

# ---- 2. 版本号三处一致 ----------------------------------------------------
Write-Step "版本号一致性"
$version = (& $python -X utf8 $buildInfo version).Trim()
& $python -X utf8 $buildInfo check | Out-Null
Write-Host "版本：$version"

# ---- 3. 门禁 --------------------------------------------------------------
if (-not $SkipGates) {
    Write-Step "门禁"
    & $python -X utf8 (Join-Path $repo "tools\check_all.py")
    if ($LASTEXITCODE -ne 0) { throw "门禁未通过，不打包" }
} else {
    Write-Host "已跳过门禁（-SkipGates）" -ForegroundColor Yellow
}

# ---- 4. 注入提交哈希 ------------------------------------------------------
Write-Step "注入构建提交"
$commit = (& git -C $repo rev-parse --short HEAD 2>$null)
if (-not $commit) { $commit = "unknown" }
$commit = $commit.Trim()
& $python -X utf8 $buildInfo write-build --commit $commit | Out-Null
Write-Host "提交：$commit"

# ---- 5. 打包 --------------------------------------------------------------
Write-Step "PyInstaller"
# **删不掉就必须停下来报错。**
#
# 实测踩过：上一次验证留下的 `--smoke` 进程还占着 dist 里的 exe，`Remove-Item`
# 抛 PermissionDenied，但脚本**继续往下跑**，PyInstaller 面对已存在的同名文件
# 又"成功"退出——于是整个构建报成功，而 dist 里还是**上一份旧产物**，
# 后面所有自检都在验旧货。这种"假成功"比直接失败危险得多。
foreach ($folder in @("dist", "build")) {
    $target = Join-Path $repo $folder
    if (-not (Test-Path $target)) { continue }
    try {
        Remove-Item $target -Recurse -Force -ErrorAction Stop
    } catch {
        # 十有八九是还有进程占着 exe；顺手把本项目自己的进程收掉再试一次
        Get-Process -Name "GUI-of-Edge-TTS" -ErrorAction SilentlyContinue |
            ForEach-Object { try { $_.Kill() } catch {} }
        Start-Sleep -Seconds 1
        try {
            Remove-Item $target -Recurse -Force -ErrorAction Stop
        } catch {
            throw "删不掉 $target —— 还有进程占着它（多半是上次 --smoke/界面没退干净）。请关掉后重试。原始错误：$($_.Exception.Message)"
        }
    }
}
& $python -X utf8 -m PyInstaller --noconfirm (Join-Path $repo "GUI-of-Edge-TTS.spec")
# 注意：**不要加 --clean**。build/ 与 dist/ 上面已经删干净了，再加 --clean
# 会让 PyInstaller 去清自己的缓存，而那个动作在 Windows 上偶发地以退出码 127
# 中途失败（实测遇到过一次，报错信息里什么都看不出来）。
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

$exe = Join-Path $repo "dist\GUI-of-Edge-TTS.exe"
if (-not (Test-Path $exe)) { throw "没有产出 $exe" }

# ---- 6. 产物自检：它自报的版本是不是这一次 --------------------------------
Write-Step "产物自检"
$reported = (& $exe --version 2>&1 | Out-String).Trim()
Write-Host "产物自报：$reported"
$expected = "$version+$commit"
if ($reported -notlike "*$expected*") {
    throw "产物自报的版本与本次构建不一致（期望包含 $expected）"
}

$selfTest = (& $exe --selftest 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    Write-Host $selfTest
    throw "产物的 --selftest 没通过"
}
foreach ($line in ($selfTest -split "`r?`n" | Where-Object { $_ -match "self" -or $_ -match "自检" })) {
    Write-Host $line
}

# ---- 7. 哈希 --------------------------------------------------------------
Write-Step "产物"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
$size = (Get-Item $exe).Length
Write-Host $exe
Write-Host ("大小 {0:N2} MB" -f ($size / 1MB))
Write-Host "SHA256 $hash"
Write-Host ""
Write-Host "打包完成。" -ForegroundColor Green
