# HermesCAD + Hermes3D installer for Windows.
#   .\install.ps1            FreeCAD add-on (junction: edits here apply after FreeCAD restart),
#                            Blender add-on (if Blender 4.2+ is installed), MCP servers, Hermes skills
#   .\install.ps1 -Copy      copy the FreeCAD add-on instead of linking
#   .\install.ps1 -NoBlender skip the Blender part
param([switch]$Copy, [switch]$NoBlender, [string]$FreeCADCmd = "", [string]$Python = "", [string]$BlenderExe = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
try { Start-Transcript -Path (Join-Path $Root "install.log") -Force | Out-Null } catch {}
trap { Write-Host "INSTALL FAILED: $_" -ForegroundColor Red; try { Stop-Transcript | Out-Null } catch {}; exit 1 }
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

# ---------------------------------------------------------------- FreeCAD
Step "Locating FreeCAD"
if (-not $FreeCADCmd) {
  $cands = @()
  foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
    if ($base -and (Test-Path $base)) {
      $cands += Get-ChildItem -Path $base -Directory -Filter "FreeCAD*" -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -Path (Join-Path $_.FullName "bin") -Filter "freecadcmd.exe" -ErrorAction SilentlyContinue }
    }
  }
  $FreeCADCmd = ($cands | Sort-Object { $_.Directory.Parent.Name } -Descending | Select-Object -First 1).FullName
}
$ModDir = $null
if ($FreeCADCmd -and (Test-Path $FreeCADCmd)) {
  Write-Host "FreeCAD: $FreeCADCmd"
  $out = & $FreeCADCmd -c "import FreeCAD;print('HCDIR='+FreeCAD.getUserAppDataDir());print('HCVER='+'.'.join(FreeCAD.Version()[:3]))" 2>$null
  $dir = ($out | Where-Object { $_ -like "HCDIR=*" } | Select-Object -First 1) -replace "^HCDIR=", ""
  $ver = ($out | Where-Object { $_ -like "HCVER=*" } | Select-Object -First 1) -replace "^HCVER=", ""
  if ($dir) { $ModDir = Join-Path $dir.Trim() "Mod"; Write-Host "FreeCAD $ver, user Mod dir: $ModDir" }
} else {
  Write-Warning "freecadcmd.exe not found; pass -FreeCADCmd 'C:\...\bin\freecadcmd.exe'. Falling back to %APPDATA%\FreeCAD\Mod"
}
if (-not $ModDir) { $ModDir = Join-Path $env:APPDATA "FreeCAD\Mod" }
New-Item -ItemType Directory -Force -Path $ModDir | Out-Null

Step "Installing the FreeCAD addon"
$src = Join-Path $Root "addon\HermesCAD"
$dst = Join-Path $ModDir "HermesCAD"
if (Test-Path $dst) {
  $item = Get-Item $dst -Force
  if ($item.LinkType) { $item.Delete() } else {
    $bak = "$dst.bak-$(Get-Date -Format yyyyMMddHHmmss)"; Move-Item $dst $bak; Write-Host "Old copy moved to $bak"
  }
}
if ($Copy) { Copy-Item -Recurse $src $dst; Write-Host "Copied to $dst" }
else { New-Item -ItemType Junction -Path $dst -Target $src | Out-Null; Write-Host "Linked $dst -> $src" }

if (Get-Process -Name "freecad","FreeCAD" -ErrorAction SilentlyContinue) {
  Write-Warning "FreeCAD is running: close it, otherwise it overwrites the settings below on exit (autostart is ON by default anyway)."
}
if ($FreeCADCmd -and (Test-Path $FreeCADCmd)) {
  # enable bridge autostart (stored in FreeCAD user.cfg)
  & $FreeCADCmd -c "import FreeCAD as A;p=A.ParamGet('User parameter:BaseApp/Preferences/Mod/HermesCAD');p.SetBool('AutoStart',True);A.saveParameter()" 2>$null | Out-Null
  Write-Host "Bridge autostart enabled (change in HermesCAD > Settings)"
}

# ------------------------------------------------------------- MCP server
Step "Python environment for the MCP server"
if (-not $Python) {
  if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py"; $pyArgs = @("-3") }
  elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python"; $pyArgs = @() }
  else { throw "Python 3.10+ not found. Install from python.org (tick 'Add to PATH') and re-run." }
} else { $pyArgs = @() }
$venv = Join-Path $Root ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { & $Python @pyArgs -m venv $venv }
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -e (Join-Path $Root "mcp_server") -q
& $vpy -c "import hermescad_mcp.server as s; print('hermescad MCP OK, tools:', len(s.mcp._tool_manager.list_tools()))"
& $vpy -c "import hermescad_mcp.blender_server as s; print('hermes3d MCP OK, tools:', len(s.mcp._tool_manager.list_tools()))"

# ------------------------------------------------------------------ Blender
$BlenderOK = $false
if (-not $NoBlender) {
  Step "Blender add-on (Hermes3D)"
  if (-not $BlenderExe) {
    $bl = @()
    foreach ($base in @($env:ProgramFiles, "$env:LOCALAPPDATA\Programs")) {
      $bf = Join-Path $base "Blender Foundation"
      if (Test-Path $bf) { $bl += Get-ChildItem -Path $bf -Recurse -Depth 1 -Filter "blender.exe" -ErrorAction SilentlyContinue }
    }
    $BlenderExe = ($bl | Sort-Object { [version](($_.Directory.Name -replace '[^0-9.]', '') + '.0') } -Descending -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
  }
  if ($BlenderExe -and (Test-Path $BlenderExe)) {
    Write-Host "Blender: $BlenderExe"
    $out = & $BlenderExe -b --factory-startup --python-expr "import bpy;print('BLDIR='+bpy.utils.user_resource('SCRIPTS', path='addons', create=True))" 2>$null
    $addons = (($out | Where-Object { $_ -like "BLDIR=*" } | Select-Object -First 1) -replace "^BLDIR=", "").Trim()
    if ($addons) {
      $bdst = Join-Path $addons "hermes3d"
      if (Test-Path $bdst) { Remove-Item -Recurse -Force $bdst }
      Copy-Item -Recurse (Join-Path $Root "blender_addon\hermes3d") $bdst
      Write-Host "Add-on copied to $bdst"
      & $BlenderExe -b --python-expr "import bpy,addon_utils;addon_utils.enable('hermes3d',default_set=True,persistent=True);bpy.ops.wm.save_userpref();print('HERMES3D_ENABLED')" 2>$null |
        Where-Object { $_ -like "HERMES3D_ENABLED*" } | ForEach-Object { Write-Host "Add-on enabled in Blender preferences" }
      Write-Host "If Blender does not show 'Hermes3D bridge' as enabled: Edit > Preferences > Add-ons > search 'Hermes3D' > tick it." -ForegroundColor Yellow
      $BlenderOK = $true
    } else { Write-Warning "Could not ask Blender for its add-ons folder; copy blender_addon\hermes3d there by hand." }
  } else {
    Write-Host "Blender not found (pass -BlenderExe 'C:\...\blender.exe'); Hermes3D part skipped." -ForegroundColor Yellow
  }
}

# ------------------------------------------------------------------ Hermes
Step "Hermes configuration"
$snippet = @"
mcp_servers:
  hermescad:
    command: '$vpy'
    args: ["-m", "hermescad_mcp"]
    env:
      HERMESCAD_HOST: "127.0.0.1"
      HERMESCAD_PORT: "9876"
      HERMESCAD_TOKEN: ""
    timeout: 300
    connect_timeout: 30
  hermes3d:
    command: '$vpy'
    args: ["-m", "hermescad_mcp.blender"]
    env:
      HERMES3D_HOST: "127.0.0.1"
      HERMES3D_PORT: "9877"
      HERMES3D_OUT: '$(Join-Path $Root "generated")'
      HF_TOKEN: ""          # optional: free Hugging Face token = bigger daily GPU quota
      TRIPO_API_KEY: ""     # optional: paid Tripo API
    timeout: 900
    connect_timeout: 60
"@
$gen = Join-Path $Root "hermes\config-snippet.generated.yaml"
Set-Content -Path $gen -Value $snippet -Encoding UTF8
$hermesHome = $null
foreach ($h in @($env:HERMES_HOME, (Join-Path $env:LOCALAPPDATA "hermes"), (Join-Path $env:USERPROFILE ".hermes"))) {
  if ($h -and (Test-Path (Join-Path $h "config.yaml"))) { $hermesHome = $h; break }
}
if ($hermesHome) {
  Write-Host "Hermes home: $hermesHome"
  foreach ($sk in @("hermescad", "hermes3d")) {
    $skillDst = Join-Path $hermesHome "skills\creative\$sk"
    New-Item -ItemType Directory -Force -Path $skillDst | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Root "hermes\skills\$sk\*") $skillDst
    Write-Host "Skill installed: $skillDst"
  }
  $cfg = Join-Path $hermesHome "config.yaml"
  if ((Test-Path $cfg) -and (Select-String -Path $cfg -Pattern "^\s+hermescad:" -Quiet) -and
      (Select-String -Path $cfg -Pattern "^\s+hermes3d:" -Quiet)) {
    Write-Host "config.yaml already has hermescad and hermes3d server entries - left untouched."
  } else {
    Write-Host "Add this to $cfg (merge under an existing mcp_servers: key if you have one):" -ForegroundColor Yellow
    Write-Host $snippet
  }
} else {
  Write-Host "Hermes config not found in HERMES_HOME, %LOCALAPPDATA%\hermes or ~\.hermes (Hermes in WSL2?). See hermes\config-snippet.yaml for the WSL variant." -ForegroundColor Yellow
}
Write-Host "Snippet saved to $gen"

Step "Done"
Write-Host "1) Restart FreeCAD -> the bridge starts automatically (or: workbench HermesCAD -> Start Hermes bridge)"
if ($BlenderOK) { Write-Host "2) Open Blender -> the Hermes3D bridge starts automatically (port 9877)" }
Write-Host "3) In Hermes: start a new chat (or /reload-mcp), then ask: 'check freecad_status' / 'check blender_status'"
Write-Host "INSTALL OK"
try { Stop-Transcript | Out-Null } catch {}
