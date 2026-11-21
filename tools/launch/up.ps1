# Lanzador de Cerberus con detección de hardware (HW2, docs/PLAN_MVP.md §25). Windows PowerShell 5.1+ y PowerShell 7.
# Mismo comportamiento que tools/launch/up.sh (macOS, Linux y WSL2).
#
#   powershell -ExecutionPolicy Bypass -File tools\launch\up.ps1              detecta y levanta el stack
#   powershell -ExecutionPolicy Bypass -File tools\launch\up.ps1 --dry-run    solo imprime lo que haría
#   powershell -ExecutionPolicy Bypass -File tools\launch\up.ps1 down         baja el stack
#
# Precedencia de variables: entorno de la terminal > `.env` de la raíz (lo lee Compose) > valor del lanzador >
# default de compose.yaml. El lanzador solo fija las variables que no están ni en el entorno ni en `.env`.
#
# Detección simulable (pruebas): CERBERUS_LAUNCH_FAKE_OS (darwin|linux|wsl|windows), CERBERUS_LAUNCH_FAKE_ARCH,
# CERBERUS_LAUNCH_FAKE_NVIDIA_SMI (CSV de nvidia-smi o «none»), CERBERUS_LAUNCH_FAKE_DOCKER_INFO («NCPU MemTotal»),
# CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES, CERBERUS_LAUNCH_ENV_FILE y CERBERUS_UV, como en up.sh.
#
# Compatible con Windows PowerShell 5.1: sin `??`, sin operador ternario y sin `&&`. Se guarda en UTF-8 con BOM
# para que 5.1 lea bien los acentos.
$ErrorActionPreference = 'Stop'
# Las funciones que llaman a ejecutables externos fijan 'Continue' en su ámbito: en Windows PowerShell 5.1, con 'Stop',
# cualquier línea de stderr de un comando nativo (aunque se redirija con 2>$null) se vuelve un error que aborta.

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root

# Umbrales. LowMemoryGB repite runtime.LOW_MEMORY_GB (pico del worker ~4.2 GB con 001/t0).
$LowMemoryGB = 5
$MemReservedGB = 2  # API (2g), Keycloak, PostgreSQL, Redis y nginx
$MemMaxGB = 12
$GpuExtraGB = 1     # contexto CUDA + cuDNN en el worker
$FewCpus = 4
$Cu126MinDriver = 525
$Cu130MinDriver = 580
# Compute capability ×10: la rueda cu126 trae kernels sm_50…sm_90; desde cc 10.0 (Blackwell) hace falta cu130
$MinCC = 50
$Cu130MinCC = 100
$GiB = 1073741824.0

$EnvFile = $env:CERBERUS_LAUNCH_ENV_FILE
if (-not $EnvFile) { $EnvFile = Join-Path $Root '.env' }

function Show-Usage {
    @'
Uso: tools\launch\up.ps1 [up|down] [opciones]

Detecta SO, arquitectura, CPU/RAM de Docker y GPU NVIDIA, y levanta Cerberus con lo mejor disponible:
  · NVIDIA (Windows/WSL2/Linux)   docker compose -f compose.yaml -f compose.gpu.yaml (torch cu126 o cu130)
  · macOS Apple Silicon           modo híbrido: compose.hybrid.yaml + worker nativo (MPS y ANTs arm64)
  · resto                         docker compose -f compose.yaml (CPU)

Opciones:
  --dry-run      imprime archivos compose, variables y comandos sin ejecutar nada
  --cpu          ignora la GPU NVIDIA
  --no-hybrid    en Mac Apple Silicon usa el worker de Docker (Rosetta) en vez del nativo
  --fast         aplica CERBERUS_REGISTRATION=fast (registro ANTs rápido) si no lo definiste tú
  --foreground   modo híbrido: el worker nativo corre en esta terminal (Ctrl+C lo detiene)
  -h, --help     esta ayuda

down: detiene el worker nativo (por su PID en storage\launch\) y baja el stack con los mismos -f del arranque.

Las variables que ya definiste (entorno o .env) nunca se sobrescriben. Ver README, «Lanzador».
'@
}

function Fail([string]$Message) {
    [Console]::Error.WriteLine("Error: $Message")
    exit 1
}

# --- argumentos ---------------------------------------------------------------------------------------------------
$Action = 'up'
$DryRun = $false; $ForceCpu = $false; $NoHybrid = $false; $Fast = $false; $Foreground = $false
foreach ($arg in $args) {
    switch ($arg) {
        'up' { $Action = 'up' }
        'down' { $Action = 'down' }
        '--dry-run' { $DryRun = $true }
        '--cpu' { $ForceCpu = $true }
        '--no-hybrid' { $NoHybrid = $true }
        '--fast' { $Fast = $true }
        '--foreground' { $Foreground = $true }
        { $_ -in @('-h', '--help', '/?') } { Show-Usage; exit 0 }
        default { Fail "opción desconocida: $arg (usa --help)" }
    }
}

# --- variables del usuario ------------------------------------------------------------------------------------------
# Valor de Name en .env (formato de Compose: KEY=VALUE, comillas opcionales, `# comentario` tras un valor sin comillas).
function Get-EnvFileValue([string]$Name) {
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { return $null }
    $pattern = '^\s*(export\s+)?' + [regex]::Escape($Name) + '\s*=(.*)$'
    $found = $null
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        $m = [regex]::Match($line, $pattern)
        if ($m.Success) { $found = $m.Groups[2].Value }
    }
    if ($null -eq $found) { return $null }
    $value = $found.TrimStart()
    if ($value.StartsWith('"')) { return ($value.Substring(1) -split '"', 2)[0] }
    if ($value.StartsWith("'")) { return ($value.Substring(1) -split "'", 2)[0] }
    return ($value -replace '\s+#.*$', '').TrimEnd()
}

function Test-UserEnv([string]$Name) {
    return $null -ne [Environment]::GetEnvironmentVariable($Name)
}

# Origen de una variable definida por el usuario («entorno» o «.env»); $null si no la definió.
function Get-UserSource([string]$Name) {
    if (Test-UserEnv $Name) { return 'entorno' }
    if ($null -ne (Get-EnvFileValue $Name)) { return '.env' }
    return $null
}

# Valor efectivo: entorno > .env > default (lo que verá Compose).
function Get-Effective([string]$Name, [string]$Default = '') {
    if (Test-UserEnv $Name) { return [Environment]::GetEnvironmentVariable($Name) }
    $fromFile = Get-EnvFileValue $Name
    if ($null -ne $fromFile) { return $fromFile }
    return $Default
}

$VarsReport = New-Object System.Collections.Generic.List[string]
$Warnings = New-Object System.Collections.Generic.List[string]
function Add-Warning([string]$Message) { $Warnings.Add("  ! $Message") }

# Fija Name=Value solo si el usuario no la definió; anota el origen en el informe.
function Set-Proposed([string]$Name, [string]$Value, [string]$Why) {
    $origin = Get-UserSource $Name
    if ($origin) {
        $VarsReport.Add("  $Name=$(Get-Effective $Name)  (tuya, $origin; el lanzador proponía $Value)")
    } else {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
        $VarsReport.Add("  $Name=$Value  (lanzador: $Why)")
    }
}

# --- detección ----------------------------------------------------------------------------------------------------
function Get-HostOS {
    if ($env:CERBERUS_LAUNCH_FAKE_OS) { return $env:CERBERUS_LAUNCH_FAKE_OS }
    # Windows PowerShell 5.1 solo existe en Windows y no define $IsWindows/$IsMacOS
    if ($PSVersionTable.PSEdition -ne 'Core') { return 'windows' }
    if ($IsWindows) { return 'windows' }
    if ($IsMacOS) { return 'darwin' }
    if ((Test-Path /proc/version) -and ((Get-Content /proc/version -Raw) -match 'microsoft')) { return 'wsl' }
    return 'linux'
}

function Get-HostArch {
    $arch = $env:CERBERUS_LAUNCH_FAKE_ARCH
    if (-not $arch) {
        $arch = $env:PROCESSOR_ARCHITEW6432  # proceso de 32 bits en Windows de 64
        if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
        if (-not $arch) {
            try { $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() } catch { $arch = '' }
        }
    }
    switch -regex ($arch) {
        '^(aarch64|arm64)$' { return 'arm64' }
        '^(x86_64|amd64|x64)$' { return 'x86_64' }
        default { return $arch }
    }
}

function Test-Command([string]$Name) { return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue) }

function Get-DockerInfo {
    $ErrorActionPreference = 'Continue'
    if ($env:CERBERUS_LAUNCH_FAKE_DOCKER_INFO) { return $env:CERBERUS_LAUNCH_FAKE_DOCKER_INFO }
    if (-not (Test-Command 'docker')) {
        Fail 'no encuentro el comando docker. Instala Docker Desktop (o Docker Engine con Compose ≥ 2.24).'
    }
    $out = & docker info --format '{{.NCPU}} {{.MemTotal}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $out) {
        Fail 'Docker no responde. Arranca Docker Desktop (o el servicio docker) y vuelve a intentarlo.'
    }
    return "$($out | Select-Object -First 1)"
}

function Get-DockerRuntimes {
    $ErrorActionPreference = 'Continue'
    if ($null -ne $env:CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES) { return $env:CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES }
    $out = & docker info --format '{{range $k, $v := .Runtimes}}{{$k}} {{end}}' 2>$null
    return "$out"
}

# Primera GPU: «nombre, compute_cap, driver, memoria»; vacío si no hay nvidia-smi o no responde.
function Get-NvidiaQuery {
    $ErrorActionPreference = 'Continue'
    if ($env:CERBERUS_LAUNCH_FAKE_NVIDIA_SMI) {
        if ($env:CERBERUS_LAUNCH_FAKE_NVIDIA_SMI -eq 'none') { return '' }
        return ($env:CERBERUS_LAUNCH_FAKE_NVIDIA_SMI -split "`n")[0]
    }
    if (-not (Test-Command 'nvidia-smi')) { return '' }
    $out = & nvidia-smi --query-gpu=name,compute_cap,driver_version,memory.total --format=csv,noheader 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $out) { return '' }
    return "$($out | Select-Object -First 1)"
}

$HostOS = Get-HostOS
$Arch = Get-HostArch
$FakeNote = ''
if ($env:CERBERUS_LAUNCH_FAKE_OS -or $env:CERBERUS_LAUNCH_FAKE_ARCH -or $env:CERBERUS_LAUNCH_FAKE_NVIDIA_SMI -or $env:CERBERUS_LAUNCH_FAKE_DOCKER_INFO) {
    $FakeNote = '  (detección simulada con CERBERUS_LAUNCH_FAKE_*)'
}

$Hybrid = ($HostOS -eq 'darwin') -and ($Arch -eq 'arm64') -and (-not $NoHybrid)

$StoragePath = Get-Effective 'CERBERUS_STORAGE_PATH' './storage'
$LaunchDir = Join-Path $StoragePath 'launch'
$PidFile = Join-Path $LaunchDir 'worker.pid'
$LogFile = Join-Path $LaunchDir 'worker.log'
$ErrLogFile = Join-Path $LaunchDir 'worker.err.log'
$StateFile = Join-Path $LaunchDir 'compose-files'

# PID del worker nativo si sigue vivo y es nuestro (evita matar un proceso ajeno que heredó el número).
function Get-NativeWorkerPid {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $text = (Get-Content -LiteralPath $PidFile -Raw) -replace '\D', ''
    if (-not $text) { return $null }
    $proc = Get-Process -Id ([int]$text) -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    if ($proc.ProcessName -notmatch '^(uv|python[0-9.]*)$') { return $null }
    return [int]$text
}

function Format-Command([string[]]$Command) { return ($Command -join ' ') }

function Invoke-Step([string[]]$Command) {
    $ErrorActionPreference = 'Continue'
    if ($DryRun) { Write-Output "  $(Format-Command $Command)"; return }
    Write-Output "+ $(Format-Command $Command)"
    $exe = $Command[0]
    $rest = @()
    if ($Command.Count -gt 1) { $rest = $Command[1..($Command.Count - 1)] }
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { Fail "falló: $(Format-Command $Command)" }
}

# --- down -----------------------------------------------------------------------------------------------------------
if ($Action -eq 'down') {
    if (Test-Path -LiteralPath $StateFile) {
        $Files = @((Get-Content -LiteralPath $StateFile -Raw).Trim() -split '\s+')
    } elseif ($Hybrid) {
        $Files = @('-f', 'compose.yaml', '-f', 'compose.hybrid.yaml')
    } else {
        $Files = @('-f', 'compose.yaml')
    }
    if ($DryRun) { Write-Output 'Comandos (--dry-run, no se ejecuta nada):' }
    $workerPid = Get-NativeWorkerPid
    if ($workerPid) {
        if ($DryRun) {
            Write-Output "  Stop-Process -Id $workerPid   # worker nativo"
        } else {
            Write-Output "Deteniendo el worker nativo (PID $workerPid)…"
            Stop-Process -Id $workerPid -ErrorAction SilentlyContinue
            Wait-Process -Id $workerPid -Timeout 30 -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        }
    } elseif (-not $DryRun) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }
    $downCmd = @('docker', 'compose') + $Files
    # Con el override híbrido, el perfil también baja un worker de Docker levantado con --profile docker-worker
    if ($Files -contains 'compose.hybrid.yaml') { $downCmd += @('--profile', 'docker-worker') }
    Invoke-Step ($downCmd + 'down')
    if (-not $DryRun) { Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue }
    exit 0
}

# --- up: decisión ---------------------------------------------------------------------------------------------------
$Info = Get-DockerInfo
$parts = @("$Info".Trim() -split '\s+')
if ($parts.Count -lt 2 -or $parts[0] -notmatch '^\d+$') { Fail "docker info devolvió CPUs no numéricas: «$Info»" }
if ($parts[1] -notmatch '^\d+$') { Fail "docker info devolvió memoria no numérica: «$Info»" }
$NCpu = [int]$parts[0]
$MemBytes = [double]$parts[1]
$MemGBValue = $MemBytes / $GiB
$MemGB = $MemGBValue.ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)

$GpuDesc = 'no detectada'
$GpuCC = ''; $GpuDriver = ''
$TorchVariant = ''
$GpuLine = ''
if ($HostOS -ne 'darwin') { $GpuLine = Get-NvidiaQuery }
if ($GpuLine) {
    $fields = @($GpuLine -split ',' | ForEach-Object { $_.Trim() })
    while ($fields.Count -lt 4) { $fields += '' }
    $GpuName = $fields[0]; $GpuCC = $fields[1]; $GpuDriver = $fields[2]; $GpuMem = $fields[3]
    $GpuDesc = "$GpuName (cc $GpuCC, driver $GpuDriver, $GpuMem)"
    $cc10 = $null
    if ($GpuCC -match '^\d+(\.\d+)?$') {
        $cc10 = [int][math]::Floor([double]::Parse($GpuCC, [Globalization.CultureInfo]::InvariantCulture) * 10 + 0.5)
    }
    $driverMajor = 0
    $majorText = ($GpuDriver -split '\.')[0]
    if ($majorText -match '^\d+$') { $driverMajor = [int]$majorText }
    if ($ForceCpu) {
        $GpuDesc = "$GpuDesc · ignorada por --cpu"
    } elseif ($null -eq $cc10) {
        Add-Warning "nvidia-smi no informó la compute capability («$GpuCC»): driver demasiado viejo. Se usa CPU."
    } elseif ($cc10 -lt $MinCC) {
        Add-Warning "la GPU tiene cc $GpuCC y PyTorch exige ≥ 5.0. Se usa CPU."
    } elseif (($HostOS -eq 'linux') -and ((Get-DockerRuntimes) -notmatch '(^|\s)nvidia(\s|$)')) {
        Add-Warning 'hay GPU NVIDIA pero Docker no tiene el runtime nvidia: instala NVIDIA Container Toolkit y reinicia Docker. Mientras tanto se usa CPU.'
    } elseif ($cc10 -ge $Cu130MinCC) {
        if ($driverMajor -ge $Cu130MinDriver) {
            $TorchVariant = 'cu130'
        } else {
            Add-Warning "la GPU (cc $GpuCC, Blackwell) necesita torch cu130 y driver ≥ $Cu130MinDriver (tienes $GpuDriver): actualiza el driver. Mientras tanto se usa CPU."
        }
    } elseif ($driverMajor -ge $Cu126MinDriver) {
        $TorchVariant = 'cu126'
    } else {
        Add-Warning "torch cu126 necesita driver NVIDIA ≥ $Cu126MinDriver (tienes $GpuDriver): actualízalo. Mientras tanto se usa CPU."
    }
}

# La imagen del backend es linux/amd64 (ANTs no publica wheel Linux arm64): en arm64 corre emulada
$Emulated = ($Arch -eq 'arm64') -and (-not $Hybrid)

$Files = @('-f', 'compose.yaml')
if ($Hybrid) {
    $Mode = 'híbrido (API en Docker + worker nativo con MPS y ANTs arm64)'
    $Files += @('-f', 'compose.hybrid.yaml')
} elseif ($TorchVariant) {
    $Mode = "gpu NVIDIA (torch $TorchVariant)"
    $Files += @('-f', 'compose.gpu.yaml')
    Set-Proposed 'CERBERUS_TORCH_VARIANT' $TorchVariant "cc $GpuCC, driver $GpuDriver"
    $effectiveVariant = Get-Effective 'CERBERUS_TORCH_VARIANT'
    if ($effectiveVariant -ne $TorchVariant) {
        Add-Warning "CERBERUS_TORCH_VARIANT=$effectiveVariant (tuya) difiere de la detectada ($TorchVariant)."
    }
} elseif ($Emulated) {
    $Mode = "cpu (backend linux/amd64 emulado en $Arch)"
} else {
    $Mode = 'cpu'
}

# Memoria del worker de Docker (en el modo híbrido no hay worker de Docker)
if (-not $Hybrid) {
    $memMin = $LowMemoryGB
    if ($TorchVariant) { $memMin = $LowMemoryGB + $GpuExtraGB }
    $limit = [int][math]::Floor($MemGBValue - $MemReservedGB)
    if ($limit -lt $memMin) { $limit = $memMin }
    if ($limit -gt $MemMaxGB) { $limit = $MemMaxGB }
    if (($MemGBValue - $MemReservedGB) -lt $memMin) {
        Add-Warning "Docker tiene $MemGB GB: tras reservar $MemReservedGB GB al resto quedan menos de $memMin GB para el worker (pico ~4.2 GB con 001/t0). Sube la memoria de Docker (Settings → Resources) o el worker puede morir por falta de memoria."
    }
    Set-Proposed 'CERBERUS_WORKER_MEM_LIMIT' "${limit}g" "clamp($MemGB GB − $MemReservedGB, $memMin, $MemMaxGB)"
}

# Registro rápido: con pocas CPU o emulación el SyN de ANTs domina el tiempo de las áreas
if (($NCpu -le $FewCpus) -or $Emulated) {
    $reason = "$NCpu CPU en Docker"
    if ($Emulated) { $reason = "emulación $Arch → amd64" }
    if ($Fast) {
        Set-Proposed 'CERBERUS_REGISTRATION' 'fast' "--fast ($reason)"
    } elseif (-not (Get-UserSource 'CERBERUS_REGISTRATION')) {
        Add-Warning "sugerencia ($reason): registro rápido con --fast o CERBERUS_REGISTRATION=fast (áreas más rápidas, con menos resolución)."
    }
} elseif ($Fast) {
    Set-Proposed 'CERBERUS_REGISTRATION' 'fast' '--fast'
}

# En Linux (y WSL2) los bind mounts respetan el UID: el contenedor debe escribir ./storage y ./models como tú
if (($HostOS -eq 'linux') -or ($HostOS -eq 'wsl')) {
    # id solo existe en Linux/WSL2 (pwsh); con la detección simulada en otro SO se usa 1000, el default de Compose
    $uid = '1000'; $gid = '1000'
    if (Test-Command 'id') { $uid = "$(& id -u)"; $gid = "$(& id -g)" }
    Set-Proposed 'CERBERUS_UID' $uid 'tu usuario'
    Set-Proposed 'CERBERUS_GID' $gid 'tu grupo'
}

$UpCmd = @('docker', 'compose') + $Files + @('up', '-d', '--build')

# Worker nativo del modo híbrido: mismas rutas que los bind mounts y Redis publicado en loopback
$UvBin = ''
$WorkerEnv = [ordered]@{}
$RedisPort = ''
if ($Hybrid) {
    $UvBin = $env:CERBERUS_UV
    if (-not $UvBin) {
        $cmd = Get-Command 'uv' -ErrorAction SilentlyContinue
        if ($cmd) { $UvBin = $cmd.Source }
    }
    if (-not $UvBin) {
        foreach ($candidate in @("$HOME/.local/bin/uv", "$HOME/.cargo/bin/uv", '/opt/homebrew/bin/uv')) {
            if (Test-Path $candidate) { $UvBin = $candidate; break }
        }
    }
    $RedisPort = Get-Effective 'CERBERUS_REDIS_PORT' '6379'
    $redisUrl = "redis://127.0.0.1:$RedisPort/0"
    if ((Test-UserEnv 'CERBERUS_REDIS_URL') -and ($env:CERBERUS_REDIS_URL -ne $redisUrl)) {
        Add-Warning "CERBERUS_REDIS_URL=$($env:CERBERUS_REDIS_URL) (tuya) se respeta, pero el Redis del stack está en $redisUrl."
        $redisUrl = $env:CERBERUS_REDIS_URL
    }
    $WorkerEnv['CERBERUS_REDIS_URL'] = $redisUrl
    foreach ($pair in @(@('DATA', './Data'), @('STORAGE', './storage'), @('MODELS', './models'))) {
        $pathValue = Get-Effective "CERBERUS_$($pair[0])_PATH" $pair[1]
        $dirName = "CERBERUS_$($pair[0])_DIR"
        if (Test-UserEnv $dirName) {
            $dirValue = [Environment]::GetEnvironmentVariable($dirName)
            if ($dirValue -ne $pathValue) {
                Add-Warning "$dirName=$dirValue (tuya) difiere de CERBERUS_$($pair[0])_PATH=${pathValue}: la API de Docker no verá esos archivos."
            }
            $WorkerEnv[$dirName] = $dirValue
        } else {
            $WorkerEnv[$dirName] = $pathValue
        }
    }
    # El worker nativo no lee .env: se le pasan los mismos valores efectivos que ve Compose
    foreach ($name in @('CERBERUS_CPU_THREADS', 'CERBERUS_REGISTRATION')) {
        $value = Get-Effective $name
        if ($value) { $WorkerEnv[$name] = $value }
    }
}
$uvShown = $UvBin
if (-not $uvShown) { $uvShown = 'uv' }
$WorkerArgs = @('run', '--no-sync', 'python', '-m', 'cerberus_api.worker')
$envShown = ($WorkerEnv.Keys | ForEach-Object { "$_=$($WorkerEnv[$_])" }) -join ' '
$WorkerShown = "env $envShown $uvShown $($WorkerArgs -join ' ')"

# --- informe ------------------------------------------------------------------------------------------------------
Write-Output "Cerberus · lanzador (HW2)$FakeNote"
Write-Output "  Sistema:  $HostOS/$Arch"
Write-Output "  Docker:   $NCpu CPU · $MemGB GB"
Write-Output "  GPU:      $GpuDesc"
Write-Output "  Modo:     $Mode"
Write-Output "  Compose:  $($Files -join ' ')"
Write-Output 'Variables:'
if ($VarsReport.Count -gt 0) { $VarsReport | ForEach-Object { Write-Output $_ } } else { Write-Output '  (ninguna)' }
if ($Warnings.Count -gt 0) { Write-Output 'Avisos:'; $Warnings | ForEach-Object { Write-Output $_ } }

if ($DryRun) {
    Write-Output 'Comandos (--dry-run, no se ejecuta nada):'
    Write-Output "  $(Format-Command $UpCmd)"
    if ($Hybrid) {
        Write-Output "  $uvShown sync"
        if ($Foreground) {
            Write-Output "  $WorkerShown"
        } else {
            Write-Output "  $WorkerShown > $LogFile 2> $ErrLogFile   # en segundo plano; PID en $PidFile"
        }
    }
    exit 0
}

# --- up: ejecución ------------------------------------------------------------------------------------------------
function Test-Preflight {
    $ErrorActionPreference = 'Continue'
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'falta Docker Compose v2 (docker compose). Actualiza Docker.' }
    if (-not $Hybrid) { return }
    if (-not $UvBin) {
        Fail 'el modo híbrido necesita uv (https://docs.astral.sh/uv/) o CERBERUS_UV=/ruta/a/uv. Alternativa: --no-hybrid.'
    }
    if (-not (Test-Command 'lsof')) { return }
    & lsof -nP "-iTCP:$RedisPort" -sTCP:LISTEN *> $null
    if ($LASTEXITCODE -ne 0) { return }
    $running = & docker compose @Files ps --status running -q redis 2>$null
    if (-not $running) {
        Fail "el puerto $RedisPort ya está en uso (¿un redis-server local?). Define CERBERUS_REDIS_PORT=6390 (u otro libre) y reintenta."
    }
}
Test-Preflight

New-Item -ItemType Directory -Force -Path $LaunchDir | Out-Null
Invoke-Step $UpCmd
Set-Content -LiteralPath $StateFile -Value ($Files -join ' ') -Encoding ASCII

$HttpPort = Get-Effective 'CERBERUS_HTTP_PORT' '8080'
if ($Hybrid) {
    $existing = Get-NativeWorkerPid
    if ($existing) {
        Write-Output "El worker nativo ya corre (PID $existing; log en $LogFile)."
    } else {
        Invoke-Step @($UvBin, 'sync')
        foreach ($key in $WorkerEnv.Keys) { [Environment]::SetEnvironmentVariable($key, $WorkerEnv[$key], 'Process') }
        if ($Foreground) {
            Write-Output "App: http://localhost:$HttpPort · worker nativo en primer plano (Ctrl+C lo detiene; después tools/launch/up.ps1 down)."
            $ErrorActionPreference = 'Continue'
            & $UvBin @WorkerArgs
            exit $LASTEXITCODE
        }
        Write-Output "+ $WorkerShown > $LogFile 2> $ErrLogFile &"
        $proc = Start-Process -FilePath $UvBin -ArgumentList $WorkerArgs -RedirectStandardOutput $LogFile `
            -RedirectStandardError $ErrLogFile -PassThru
        Set-Content -LiteralPath $PidFile -Value $proc.Id -Encoding ASCII
        Start-Sleep -Seconds 3
        if (-not (Get-NativeWorkerPid)) { Fail "el worker nativo terminó al arrancar; revisa $LogFile y $ErrLogFile" }
        Write-Output "Worker nativo en segundo plano (PID $($proc.Id); log en $LogFile)."
    }
}
Write-Output "App: http://localhost:$HttpPort · para bajar: tools/launch/up.ps1 down"
