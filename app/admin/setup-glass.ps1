<#  setup-glass.ps1  (v2 – auto-detects src)
    Usage:
      .\setup-glass.ps1 -ProjectRoot "C:\path\to\Glass"
#>

param(
  [string]$Python = "py",
  [Parameter(Mandatory=$false)]
  [string]$ProjectRoot = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
Write-Host "== GLASS: setup & build ==" -ForegroundColor Cyan

function Resolve-GlassLayout {
  param([string]$Root)
  $entry = Get-ChildItem -Path $Root -Filter "main_gui.py" -Recurse -ErrorAction SilentlyContinue |
           Select-Object -First 1
  if (-not $entry) {
    throw "Couldn't find main_gui.py under `$Root`. Pass -ProjectRoot to your Glass folder."
  }
  $Src = Split-Path $entry.FullName -Parent
  $CandidateRoot = (Split-Path $Src -Parent)
  $Assets = Join-Path $CandidateRoot "assets"
  if (-not (Test-Path $Assets)) { $Assets = Join-Path $Root "assets" }
  return [PSCustomObject]@{
    Entry   = $entry.FullName
    Src     = $Src
    Root    = (Split-Path $Assets -Parent)
    Assets  = $Assets
  }
}

# ---- Resolve layout
$layout = Resolve-GlassLayout -Root $ProjectRoot
$Src    = $layout.Src
$Root   = $layout.Root
$Assets = $layout.Assets
$Entry  = $layout.Entry

Write-Host "Project root : $Root"  -ForegroundColor DarkGray
Write-Host "Source folder: $Src"   -ForegroundColor DarkGray
Write-Host "Assets folder: $Assets" -ForegroundColor DarkGray
Write-Host "Entry point  : $Entry" -ForegroundColor DarkGray

$Dist    = Join-Path $Root "dist"
$Build   = Join-Path $Root "build"
$VenvDir = Join-Path $Root ".venv"

# ---- Remove duplicate modules at root (keep src/ copies)
$dupes = @("hwid.py","net.py","paths.py","theme.py","overlay.py","globe_widget.py","window_utils.py","transparency.py","settings.py")
$removed = @()
foreach ($f in $dupes) {
  $rootPath = Join-Path $Root $f
  $srcPath  = Join-Path $Src $f
  if ((Test-Path $rootPath) -and (Test-Path $srcPath)) {
    $bak = "$rootPath.bak_removed"
    Move-Item -Force $rootPath $bak
    $removed += $f
  }
}
if ($removed.Count -gt 0) {
  Write-Host "Removed duplicate root modules (backed up as *.bak_removed): $($removed -join ', ')" -ForegroundColor Yellow
}

# ---- Ensure assets exist
if (-not (Test-Path $Assets)) {
  New-Item -ItemType Directory -Force $Assets | Out-Null
  Write-Warning "Created empty assets/ folder (no icon found)."
}
$icon = Join-Path $Assets "icon.ico"
$iconFlag = @()
if (Test-Path $icon) { $iconFlag = @("--icon", $icon) } else { Write-Warning "assets\icon.ico not found (EXE will use default icon)." }

# ---- VENV + PyInstaller
if (-not (Test-Path $VenvDir)) {
  Write-Host "Creating virtual env at $VenvDir ..." -ForegroundColor Cyan
  & $Python -m venv $VenvDir
}
. (Join-Path $VenvDir "Scripts\Activate.ps1")
pip install --upgrade pip | Out-Null
pip install --upgrade pyinstaller | Out-Null

# ---- Overlay sanity (optional)
$OverlayFile = Join-Path $Src "overlay.py"
if (Test-Path $OverlayFile) {
  $overlayText = Get-Content $OverlayFile -Raw
  if ($overlayText -notmatch "class\s+TraceOverlay") {
    Write-Warning "overlay.py does not define class TraceOverlay (Overlay Lock may be disabled)."
  }
} else {
  Write-Warning "overlay.py not found in $Src"
}

# ---- Clean old build
Write-Host "Cleaning build artifacts..." -ForegroundColor Cyan
Remove-Item -Recurse -Force -ErrorAction Ignore $Build, $Dist

# ---- Build
$addData = "$Assets;assets"   # bundle assets/ → runtime assets/
Write-Host "Building Glass.exe..." -ForegroundColor Cyan
$piArgs = @(
  "--name","Glass",
  "--noconsole",
  "--clean",
  "--add-data",$addData
) + $iconFlag + @($Entry)

pyinstaller @piArgs

# ---- Results
Write-Host ""
$exePath = Join-Path $Dist "Glass\Glass.exe"
if (Test-Path $exePath) {
  Write-Host "Build complete: $exePath" -ForegroundColor Green
} else {
  Write-Warning "Build finished but Glass.exe not found in dist\Glass\ — check PyInstaller output above."
}

Write-Host ""
Write-Host "== Quick commands ==" -ForegroundColor Cyan
Write-Host "Dev run:" -ForegroundColor DarkGray
Write-Host "  .\.venv\Scripts\Activate.ps1; py -X utf8 `"$Entry`""
Write-Host "Rebuild:" -ForegroundColor DarkGray
Write-Host "  .\.venv\Scripts\Activate.ps1; pyinstaller --name Glass --noconsole --add-data `"$Assets;assets`" $($iconFlag -join ' ') `"$Entry`""
