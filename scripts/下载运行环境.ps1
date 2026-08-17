# ============================================================
#  下载便携运行环境（Python）到 runtime\ 目录
#  供「一键启动.bat」在电脑上没有 Python 时自动调用
# ============================================================
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # 加速下载

$root = Split-Path -Parent $PSScriptRoot      # 项目根目录
$runtime = Join-Path $root "runtime"

$pyVersion = "3.13.14"
$arch = "amd64"

$pyZipName = "python-$pyVersion-embed-$arch.zip"
$pyZip = Join-Path $env:TEMP $pyZipName
$pyUrl = "https://www.python.org/ftp/python/$pyVersion/$pyZipName"

$getpip = Join-Path $runtime "get-pip.py"

Write-Host "  [1/3] 正在下载运行环境..." -ForegroundColor Cyan
try {
    if (-not (Test-Path $pyZip)) {
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyZip -UseBasicParsing
    }
} catch {
    Write-Host "  ✗ 下载失败，请检查网络后重试。" -ForegroundColor Red
    exit 1
}

Write-Host "  [2/3] 正在解压运行环境..." -ForegroundColor Cyan
try {
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Expand-Archive -Path $pyZip -DestinationPath $runtime -Force
} catch {
    Write-Host "  ✗ 解压失败，请重新运行。" -ForegroundColor Red
    exit 1
}

# 让 Python 能正常使用扩展包（修正 ._pth 配置）
Get-ChildItem -Path $runtime -Filter "python*._pth" | ForEach-Object {
    @("python313.zip", ".", "Lib\site-packages", "import site") |
        Set-Content -Path $_.FullName -Encoding ASCII
}

Write-Host "  [3/3] 正在安装扩展包管理工具..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip -UseBasicParsing
    & (Join-Path $runtime "python.exe") $getpip --no-warn-script-location | Out-Null
    Remove-Item $getpip -Force -ErrorAction SilentlyContinue
} catch {
    Write-Host "  ✗ 安装扩展工具失败，请检查网络后重试。" -ForegroundColor Red
    exit 1
}

Write-Host "  ✓ 运行环境准备完成。" -ForegroundColor Green
exit 0
