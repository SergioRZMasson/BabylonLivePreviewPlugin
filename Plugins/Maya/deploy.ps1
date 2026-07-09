# ---------------------------------------------------------------------------
# Deploy the Maya plugin as a relocatable Maya module.
#
#   powershell -File Plugins\Maya\deploy.ps1
#
# Produces dist\maya\ with a .mod file + the .mll, its bundled runtime DLLs, and
# the Scripts/ bundle. A Maya module adds plug-ins/ to MAYA_PLUG_IN_PATH and the
# `PATH +:=` line prepends it to the process PATH so the .mll's own dependent
# DLLs (v8.dll, ...) resolve — Maya's loadPlugin otherwise ignores
# add_dll_directory/PATH for a plugin's private deps.
# ---------------------------------------------------------------------------
param(
    [string]$Config = "Release"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$build = Join-Path $repo "build\Plugins\Maya\$Config"
$mll = Join-Path $build "babylonLivePreview.mll"
if (-not (Test-Path $mll)) {
    throw "Build the Maya plugin first (cmake --build --preset windows-x64-release --target BabylonLivePreviewMaya). Missing: $mll"
}

$distRoot = Join-Path $repo "dist\maya"
$moduleRoot = Join-Path $distRoot "BabylonLivePreview"
$plugins = Join-Path $moduleRoot "plug-ins"

if (Test-Path $moduleRoot) { Remove-Item $moduleRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $plugins | Out-Null

# Copy the .mll + every bundled runtime DLL/data + the Scripts/ folder.
Copy-Item $mll $plugins -Force
Get-ChildItem $build -File | Where-Object { $_.Extension -in ".dll", ".dat" } |
    ForEach-Object { Copy-Item $_.FullName $plugins -Force }
Copy-Item (Join-Path $build "Scripts") $plugins -Recurse -Force

# Write the module file. Maya auto-adds <root>/plug-ins to MAYA_PLUG_IN_PATH;
# PATH +:= plug-ins makes the bundled DLLs resolvable at load time.
$modBody = @"
+ MAYAVERSION:2024 PLATFORM:win64 BabylonLivePreview 0.1.0 $moduleRoot
PATH +:= plug-ins
"@
$modPath = Join-Path $distRoot "BabylonLivePreview.mod"
Set-Content -Path $modPath -Value $modBody -Encoding ascii

Write-Host "Deployed Maya module to: $distRoot"
Write-Host ""
Write-Host "To use in Maya 2024:"
Write-Host "  1. Set the env var MAYA_MODULE_PATH to include: $distRoot"
Write-Host "     (or copy $modPath into your Maya\2024\modules folder and fix the path)"
Write-Host "  2. Start Maya, open Windows > Settings/Preferences > Plug-in Manager"
Write-Host "  3. Load 'babylonLivePreview.mll'"
Write-Host "  4. Run MEL:  babylonLivePreview -start;"
Write-Host "  5. Open Windows > Rendering Editors > Render View to see the live preview."
