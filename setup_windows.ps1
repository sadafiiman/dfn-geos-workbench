#Requires -Version 5.1
<#
    dfnWorks -> GEOS Workbench : one-shot Windows setup
    ---------------------------------------------------
    What it does, in order:
        1. checks Git, Python and Docker Desktop
        2. downloads the two required projects (dfnWorks, this workbench)
           into -Root (default C:\dfn-project)
        3. installs the only Python dependency (numpy)
        4. pulls the dfnWorks container image
        5. (optional, -WithGeos) builds the GEOS solver image once
        6. writes the panel configuration
        7. starts the panel and opens the browser

    Quick start (from the folder that contains this file):
        powershell -ExecutionPolicy Bypass -File setup_windows.ps1

    Useful options:
        -WithGeos     also build the GEOS solver image (~45-60 min, ~8 GB)
        -NoStart      set everything up but do not launch the panel
        -Force        overwrite an existing config.json
        -Root D:\dfn  use a different folder
        -Port 9000    use a different port
#>
[CmdletBinding()]
param(
    [string] $Root = "C:\dfn-project",
    [int]    $Port = 8765,
    [switch] $WithGeos,
    [switch] $NoStart,
    [switch] $Force
)

$ErrorActionPreference = "Stop"

$DFNWORKS_REPO   = "https://github.com/lanl/dfnWorks.git"
$WORKBENCH_REPO  = "https://github.com/sadafiiman/dfn-geos-workbench.git"
$GEOS_REPO       = "https://github.com/GEOS-DEV/GEOS.git"
$DFN_IMAGE       = "ees16/dfnworks:latest"
$TPL_IMAGE       = "geosx/ubuntu24.04-gcc13:364-1112"
$GEOS_IMAGE      = "dfn-geos:1.1"

function Step($n, $text) {
    Write-Host ""
    Write-Host "[$n/7] $text" -ForegroundColor Cyan
}
function Ok($text)   { Write-Host "      $text" -ForegroundColor Green }
function Note($text) { Write-Host "      $text" -ForegroundColor DarkGray }
function Fail($text) {
    Write-Host ""
    Write-Host "ERROR: $text" -ForegroundColor Red
    Write-Host ""
    exit 1
}

function Find-Python {
    $candidates = @("py -3", "python", "python3")
    foreach ($c in $candidates) {
        $parts = @($c.Split(" "))
        $name  = $parts[0]
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { continue }
        $extra = @()
        if ($parts.Length -gt 1) { $extra = $parts[1..($parts.Length - 1)] }
        try {
            $out = & $name @extra -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                return ([string]($out | Select-Object -Last 1)).Trim()
            }
        } catch { }
    }
    return $null
}

function Ensure-Repo($url, $dest) {
    if (Test-Path (Join-Path $dest ".git")) {
        Ok "$dest already cloned"
        return
    }
    if (Test-Path $dest) { Fail "$dest exists but is not a git repository - move it away first" }
    # autocrlf off: the GEOS sources are compiled inside a Linux container.
    git -c core.autocrlf=false clone --depth 1 $url $dest
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed for $url" }
    Ok "cloned $dest"
}

function Test-Image($name) {
    docker image inspect $name *> $null
    return ($LASTEXITCODE -eq 0)
}

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "  dfnWorks -> GEOS Workbench - Windows setup" -ForegroundColor White
Write-Host "  project folder: $Root" -ForegroundColor DarkGray
Write-Host "  panel port    : $Port" -ForegroundColor DarkGray

# 1 --- prerequisites ------------------------------------------------------
Step 1 "Checking Git, Python and Docker"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "Git is not installed. Get it from https://git-scm.com/download/win and reopen this window."
}
Ok ("git " + ((git --version) -replace "git version ", ""))

$python = Find-Python
if (-not $python) {
    Fail "Python is not installed. Get it from https://python.org/downloads and tick 'Add python.exe to PATH'."
}
Ok ("python " + (& $python -c "import platform; print(platform.python_version())").Trim())

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker Desktop is not installed. Get it from https://docker.com/products/docker-desktop"
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Note "Docker Desktop is not running - starting it (this can take a minute) ..."
        Start-Process $dockerExe
        $ready = $false
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 2
            docker info *> $null
            if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        }
        if (-not $ready) { Fail "Docker Desktop did not start. Open it manually, wait for 'Engine running', then run this script again." }
    } else {
        Fail "Docker Desktop is not running. Open it, wait for 'Engine running', then run this script again."
    }
}
Ok "docker engine is running"

# 2 --- projects -----------------------------------------------------------
Step 2 "Downloading the project code into $Root"

New-Item -ItemType Directory -Force -Path $Root | Out-Null
$dfnDir  = Join-Path $Root "dfnWorks"
$workDir = Join-Path $Root "dfn-geos-workbench"

# If this script is already inside a clone, use that clone instead of a second copy.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ((Test-Path (Join-Path $here "run_panel.py")) -and
    (Test-Path (Join-Path $here "panel"))) {
    $workDir = $here
    Ok "using the workbench that contains this script: $workDir"
} else {
    Ensure-Repo $WORKBENCH_REPO $workDir
}
Ensure-Repo $DFNWORKS_REPO $dfnDir

# 3 --- python dependency --------------------------------------------------
Step 3 "Checking the Python dependency (numpy)"

& $python -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "this Python cannot run pip. Reinstall Python from python.org (tick 'Add python.exe to PATH' and 'pip')."
}

& $python -c "import numpy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Note "numpy is missing - installing it ..."
    & $python -m pip install --quiet numpy
    if ($LASTEXITCODE -ne 0) { Fail "could not install numpy - check the network / proxy and try again" }
    & $python -c "import numpy" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "numpy still cannot be imported after installing it" }
    Ok "numpy installed"
} else {
    Ok "numpy already present"
}

# 4 --- dfnWorks image -----------------------------------------------------
Step 4 "Pulling the dfnWorks container image ($DFN_IMAGE)"

docker pull $DFN_IMAGE
if ($LASTEXITCODE -ne 0) { Fail "docker pull failed - check that Docker Desktop is running and you are online" }
Ok "image ready"

# 5 --- optional GEOS solver ----------------------------------------------
$geosReady = $false
if ($WithGeos) {
    Step 5 "Building the GEOS solver image ($GEOS_IMAGE) - this is the long step"

    if (Test-Image $GEOS_IMAGE) {
        Ok "$GEOS_IMAGE already exists - skipping the build"
    } else {
        $geosDir = Join-Path $Root "GEOS"
        Ensure-Repo $GEOS_REPO $geosDir

        docker pull $TPL_IMAGE
        if ($LASTEXITCODE -ne 0) { Fail "docker pull failed for $TPL_IMAGE" }

        # Build inside the container (fast local disk), not on a bind mount:
        # /mnt/c is several times slower and this is a 3000-file C++ build.
        docker rm -f geosbuild *> $null
        Note "starting the build container and copying the GEOS source ..."
        docker run -d --name geosbuild $TPL_IMAGE sleep infinity | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "could not start the build container $TPL_IMAGE" }
        docker cp $geosDir geosbuild:/opt/GEOS
        if ($LASTEXITCODE -ne 0) { Fail "could not copy the GEOS source into the container" }

        Note "downloading submodules (1/4) - several GB, no output for a while ..."
        docker exec geosbuild bash -lc "git config --global --add safe.directory '*' && cd /opt/GEOS && git submodule update --init --recursive"
        if ($LASTEXITCODE -ne 0) { docker rm -f geosbuild *> $null; Fail "could not fetch the GEOS submodules" }

        Note "configuring (2/4) ..."
        docker exec geosbuild bash -lc "cd /opt/GEOS && python3 scripts/config-build.py -hc /spack-generated.cmake -bt Release -bp /work/geos-build -ip /work/geos-install -DENABLE_HYPRE=ON -DENABLE_TRILINOS=OFF -DGEOS_LA_INTERFACE=Hypre -DENABLE_TESTS=OFF -DENABLE_EXAMPLES=OFF -DENABLE_BENCHMARKS=OFF -DDISABLE_UNIT_TESTS=ON"
        if ($LASTEXITCODE -ne 0) { docker rm -f geosbuild *> $null; Fail "GEOS configure failed" }

        Note "compiling (3/4) - expect 30-60 minutes with no output ..."
        docker exec geosbuild bash -lc "cd /work/geos-build && make -j4 geosx"
        if ($LASTEXITCODE -ne 0) { docker rm -f geosbuild *> $null; Fail "GEOS build failed (low memory? edit -j4 in this script and try again)" }

        Note "packaging the image (4/4) ..."
        docker exec geosbuild bash -lc "rm -rf /opt/geos && mkdir -p /opt/geos && cp -a /work/geos-build/. /opt/geos/"
        if ($LASTEXITCODE -ne 0) { docker rm -f geosbuild *> $null; Fail "could not copy the GEOS build to /opt/geos" }
        docker commit -c "ENV LD_LIBRARY_PATH=/opt/geos/lib" geosbuild $GEOS_IMAGE | Out-Null
        if ($LASTEXITCODE -ne 0) { docker rm -f geosbuild *> $null; Fail "could not create the image $GEOS_IMAGE" }
        docker rm -f geosbuild *> $null
        Ok "created $GEOS_IMAGE (solver at /opt/geos/bin/geosx)"
    }
    $geosReady = $true
} else {
    Step 5 "GEOS solver - skipped (add -WithGeos to build it)"
    Note "without it you still get the mesh and the GEOS input decks;"
    Note "only the 'Run GEOS' stage is unavailable."
}

# 6 --- configuration ------------------------------------------------------
Step 6 "Writing the panel configuration"

$configPath = Join-Path $workDir "config.json"
if ((Test-Path $configPath) -and (-not $Force)) {
    Ok "config.json already exists - kept (use -Force to overwrite)"
} else {
    $config = [ordered]@{
        dfnworks_backend      = "docker"
        dfnworks_docker_image = $DFN_IMAGE
        dfnworks_path         = $dfnDir
        lagrit_exe            = ""
        geos_backend          = if ($geosReady) { "docker" } else { "auto" }
        geos_docker_image     = if ($geosReady) { $GEOS_IMAGE } else { "" }
        geos_exe              = ""
        python_exe            = $python
        panel_port            = $Port
        use_compat_pythonpath = $true
    }
    $json = $config | ConvertTo-Json
    [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))
    Ok "wrote $configPath"
}

# A previous run may have left the GEOS solver unconfigured (it is opt-in).
# If the image is there now, enable it - no -Force needed.
if ($geosReady) {
    $cfg = [System.IO.File]::ReadAllText($configPath) | ConvertFrom-Json
    if (($cfg.geos_docker_image -ne $GEOS_IMAGE) -or ($cfg.geos_backend -ne "docker")) {
        $cfg.geos_backend      = "docker"
        $cfg.geos_docker_image = $GEOS_IMAGE
        $json = $cfg | ConvertTo-Json
        [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        Ok "enabled the GEOS solver in config.json"
    }
}

# 7 --- start --------------------------------------------------------------
Step 7 "Starting the panel"

$url = "http://localhost:$Port"
if ($NoStart) {
    Note "skipped (-NoStart). Start it later with:"
    $scriptPath = Join-Path $workDir "run_panel.py"
    Write-Host "      `"$python`" `"$scriptPath`" --port $Port" -ForegroundColor White
} else {
    $cmd = "Set-Location -LiteralPath '$workDir'; & '$python' run_panel.py --port $Port"
    Start-Process -FilePath "powershell.exe" `
                  -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd) `
                  -WorkingDirectory $workDir | Out-Null
    Start-Sleep -Seconds 4
    Start-Process $url
    Ok "panel window opened; browser -> $url"
}

Write-Host ""
Write-Host "  Setup finished." -ForegroundColor Green
if ($WithGeos) {
    Write-Host "  All three stages are available (dfnWorks mesh -> convert -> GEOS run)."
} else {
    Write-Host "  Stages 1-2 work now (mesh + GEOS decks); stage 3 needs -WithGeos."
}
Write-Host "  Next time, just run start_windows.cmd" -ForegroundColor DarkGray
Write-Host ""
