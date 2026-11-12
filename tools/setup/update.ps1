# Actualización explícita y recuperación en destinos nuevos. Nunca borra volúmenes.
[CmdletBinding(DefaultParameterSetName = 'Update')]
param(
    [Parameter(Mandatory = $true, Position = 0, ParameterSetName = 'Update')][string]$Candidate,
    [Parameter(Mandatory = $true, ParameterSetName = 'Backup')][switch]$Backup,
    [Parameter(Mandatory = $true, ParameterSetName = 'Rollback')][ValidatePattern('^[a-f0-9]{40}$')][string]$Rollback,
    [Parameter(Mandatory = $true, ParameterSetName = 'Restore')][string]$Restore,
    [Parameter(Mandatory = $true, ParameterSetName = 'Restore')][string]$Destination,
    [Parameter(Mandatory = $true, ParameterSetName = 'Restore')][ValidatePattern('^cerberus-(restore|qa)-[a-z0-9][a-z0-9_-]{0,49}$')][string]$Project
)
$ErrorActionPreference = 'Stop'
$installation = if ($env:CERBERUS_INSTALL_DIR) { $env:CERBERUS_INSTALL_DIR } else { Join-Path $PSScriptRoot '../..' }
$installation = (Resolve-Path -LiteralPath $installation).Path
$mode = $PSCmdlet.ParameterSetName
$runtimeProject = $Project
$paused = $false
$activated = $false
$dumpCreated = $false
$lock = $null
$exitCode = 1
$volumeNames = @('redis-data', 'auth-db-data', 'keycloak-data', 'auth-db-secret', 'keycloak-admin-secret', 'oidc-client-secret')
$imagePattern = '^[a-z0-9./:_-]+@sha256:[a-f0-9]{64}$'

function Invoke-Docker {
    param([string[]]$Arguments)
    # No se imprimen errores nativos: pueden incluir rutas o configuración privada.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $result = & docker @Arguments 2>&1; $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previousPreference }
    if ($code -ne 0) { throw 'Docker no pudo completar la operación.' }
    return ($result | Out-String).Trim()
}
function Invoke-Compose {
    param([string[]]$Arguments)
    Invoke-Docker -Arguments (@('compose', '--project-directory', $installation, '-f', (Join-Path $installation 'compose.yaml'), '-p', $runtimeProject) + $Arguments)
}
function Set-Private {
    param([string]$Path, [switch]$Directory)
    if ($env:OS -eq 'Windows_NT') {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleSpecific($rule) }
        $inheritance = if ($Directory) { 'ContainerInherit,ObjectInherit' } else { 'None' }
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', $inheritance, 'None', 'Allow')
        $acl.SetAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } else {
        $permission = if ($Directory) { '700' } else { '600' }
        & chmod $permission $Path
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo proteger el backup.' }
    }
}
function Invoke-Guard {
    Invoke-Compose -Arguments @('run', '--rm', '--no-deps', '--pull', 'never', '-T', '--entrypoint', 'python',
        '--volume', "${installation}:/release/current:ro", '--volume', "${Candidate}:/release/candidate:ro", 'api',
        '-m', 'cerberus_api.release_state', '--current', '/release/current', '--candidate', '/release/candidate') | Out-Null
}
$isolatedHelper = @('run', '--rm', '--pull', 'never', '--network', 'none', '--platform', 'linux/amd64',
    '--read-only', '--tmpfs', '/tmp', '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL')
$rootHelper = $isolatedHelper + @('--user', '0:0', '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'FOWNER', '--entrypoint', 'python')
try {
    Get-Command docker -ErrorAction Stop | Out-Null
    Invoke-Docker -Arguments @('info') | Out-Null
    $endpoint = $env:DOCKER_HOST
    if ($env:DOCKER_CONTEXT) { $endpoint = Invoke-Docker -Arguments @('context', 'inspect', $env:DOCKER_CONTEXT, '--format', '{{.Endpoints.docker.Host}}') }
    elseif (-not $endpoint) { $endpoint = Invoke-Docker -Arguments @('context', 'inspect', '--format', '{{.Endpoints.docker.Host}}') }
    if ($endpoint -notmatch '^(unix|npipe)://') { throw 'Se requiere contexto Docker local.' }
    if ($mode -eq 'Restore') {
        $backupPath = (Resolve-Path -LiteralPath $Restore).Path
        if (-not (Test-Path -LiteralPath $Destination)) { New-Item -ItemType Directory -Path $Destination | Out-Null }
        $Destination = (Resolve-Path -LiteralPath $Destination).Path
        if (@(Get-ChildItem -LiteralPath $Destination -Force).Count -ne 0) { throw 'El destino debe estar vacío.' }
        $lockRoot = $Destination
    } else {
        if ($mode -eq 'Rollback') { $Candidate = Join-Path $installation ".cerberus-versions/$Rollback" }
        if ($mode -eq 'Backup') { $Candidate = $installation } else { $Candidate = (Resolve-Path -LiteralPath $Candidate).Path }
        if ($Candidate -eq $installation -and $mode -ne 'Backup') { throw 'El candidato debe estar en otra carpeta.' }
        $fileProject = ''
        $envPath = Join-Path $installation '.env'
        if (Test-Path -LiteralPath $envPath) {
            foreach ($line in Get-Content -LiteralPath $envPath) {
                if ($line -match '^COMPOSE_PROJECT_NAME=(.*)$') {
                    $fileProject = $Matches[1].Trim()
                    if ($fileProject -match '^(["''])(.*)\1$') { $fileProject = $Matches[2] }
                }
            }
        }
        $runtimeProject = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } elseif ($fileProject) { $fileProject } else { 'cerberus' }
        if ($runtimeProject -cnotmatch '^[a-z0-9][a-z0-9_-]*$') { throw 'Proyecto inválido.' }
        $lockRoot = $installation
    }
    $existing = Invoke-Docker -Arguments @('ps', '-a', '--filter', "label=com.docker.compose.project=$runtimeProject", '--format', '{{.ID}}')
    foreach ($container in @($existing -split '\r?\n' | Where-Object { $_ })) {
        if ($mode -eq 'Restore') { throw 'La restauración requiere proyecto nuevo.' }
        $directory = Invoke-Docker -Arguments @('inspect', '--format', '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}', $container)
        $directory = (Resolve-Path -LiteralPath $directory).Path
        if ($directory -ne $installation) { throw 'Este proyecto pertenece a otra carpeta.' }
    }
    $lockPath = Join-Path $lockRoot '.cerberus-setup.lock'
    # CreateDirectory no es exclusivo; mkdir nativo tampoco lo es en PowerShell. La
    # creación atómica usa el mismo directorio exclusivo que los lanzadores de inicio.
    $lockClaim = Join-Path $lockRoot ('.cerberus-lock-' + [guid]::NewGuid().ToString('N'))
    [void][System.IO.Directory]::CreateDirectory($lockClaim)
    try { [System.IO.Directory]::Move($lockClaim, $lockPath); $lock = $lockPath }
    finally { if (Test-Path -LiteralPath $lockClaim) { [System.IO.Directory]::Delete($lockClaim) } }

    if ($mode -eq 'Restore') {
        $helper = (Get-Content -LiteralPath (Join-Path $backupPath 'helper-image.txt') -Raw).Trim()
        if ($helper -cnotmatch $imagePattern) { throw 'Imagen de recuperación inválida.' }
        Invoke-Docker -Arguments @('image', 'inspect', $helper) | Out-Null
        Invoke-Docker -Arguments ($isolatedHelper + @('--entrypoint', 'python', '--volume', "${backupPath}:/backup:ro", $helper,
            '-m', 'cerberus_api.release_state', '--operation', 'verify-backup', '--backup', '/backup')) | Out-Null
        $mounts = @()
        foreach ($volume in $volumeNames) {
            $exists = $false
            try { Invoke-Docker -Arguments @('volume', 'inspect', "${Project}_${volume}") | Out-Null; $exists = $true } catch { }
            if ($exists) { throw 'La restauración requiere volúmenes nuevos.' }
            $mounts += @('--volume', "${Project}_${volume}:/run/cerberus-backup/$volume")
        }
        Invoke-Docker -Arguments ($rootHelper + @('--volume', "${backupPath}:/backup:ro", '--volume', "${Destination}:/restore") + $mounts +
            @($helper, '-m', 'cerberus_api.release_state', '--operation', 'restore', '--backup', '/backup', '--destination', '/restore', '--project', $Project)) | Out-Null
        Write-Host 'Restauración preparada en proyecto nuevo, sin iniciar servicios. Revisa puertos y ejecuta su lanzador.'
    } else {
        $helper = Invoke-Compose -Arguments @('config', '--images', 'api')
        if ($helper -cnotmatch $imagePattern) { throw 'La instalación requiere una release con digest.' }
        Invoke-Docker -Arguments @('image', 'inspect', $helper) | Out-Null
        Invoke-Guard
        if ($mode -ne 'Backup') {
            Write-Host 'Descargando versión explícita; la instalación actual continúa disponible.'
            Invoke-Docker -Arguments @('compose', '--project-directory', $installation, '-f', (Join-Path $Candidate 'compose.yaml'), '-p', $runtimeProject, 'pull') | Out-Null
            $labels = @{}
            foreach ($component in @('backend', 'frontend')) {
                $service = if ($component -eq 'backend') { 'api' } else { 'frontend' }
                $image = Invoke-Docker -Arguments @('compose', '--project-directory', $installation, '-f', (Join-Path $Candidate 'compose.yaml'), '-p', $runtimeProject, 'config', '--images', $service)
                $template = '{"version":{{json (index .Config.Labels "org.opencontainers.image.version")}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},"architecture":{{json .Architecture}},"os":{{json .Os}}}'
                $labels[$component] = (Invoke-Docker -Arguments @('image', 'inspect', '--format', $template, $image)) | ConvertFrom-Json
            }
            $labelsPath = Join-Path $lock 'labels.json'
            [System.IO.File]::WriteAllText($labelsPath, ($labels | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
            Invoke-Compose -Arguments @('run', '--rm', '--no-deps', '--pull', 'never', '-T', '--entrypoint', 'python',
                '--volume', "${installation}:/release/current:ro", '--volume', "${Candidate}:/release/candidate:ro", '--volume', "${labelsPath}:/release/labels.json:ro", 'api',
                '-m', 'cerberus_api.release_state', '--operation', 'verify-images', '--current', '/release/current', '--candidate', '/release/candidate', '--labels', '/release/labels.json') | Out-Null
        }
        Write-Host 'Pausando aplicación y comprobando de nuevo la cola.'
        $paused = $true
        Invoke-Compose -Arguments @('stop', 'frontend', 'api', 'worker') | Out-Null
        Invoke-Guard
        Invoke-Compose -Arguments @('stop', 'keycloak') | Out-Null
        $backupPath = Join-Path $installation ('.cerberus-backups/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + $PID)
        New-Item -ItemType Directory -Path $backupPath | Out-Null
        Set-Private -Path $backupPath -Directory
        Invoke-Compose -Arguments @('exec', '-T', 'auth-db', 'sh', '-ec', 'umask 077; test ! -e /tmp/cerberus-update.dump; trap "rm -f /tmp/cerberus-update.dump" EXIT; pg_dump -U keycloak -d keycloak -Fc -f /tmp/cerberus-update.dump; trap - EXIT') | Out-Null
        $dumpCreated = $true
        $database = Invoke-Compose -Arguments @('ps', '-q', 'auth-db')
        if ($database -cnotmatch '^[a-f0-9]{12,64}$') { throw 'Contenedor de base inválido.' }
        Invoke-Docker -Arguments @('cp', "${database}:/tmp/cerberus-update.dump", (Join-Path $backupPath 'database.dump')) | Out-Null
        Invoke-Compose -Arguments @('exec', '-T', 'auth-db', 'rm', '/tmp/cerberus-update.dump') | Out-Null
        $dumpCreated = $false
        Set-Private -Path (Join-Path $backupPath 'database.dump')
        Invoke-Compose -Arguments @('exec', '-T', 'redis', 'redis-cli', 'SAVE') | Out-Null
        Invoke-Compose -Arguments @('stop', 'auth-db', 'redis') | Out-Null
        $mounts = @()
        foreach ($specification in @('redis-data:redis:/data', 'auth-db-data:auth-db:/var/lib/postgresql',
            'keycloak-data:keycloak:/opt/keycloak/data', 'auth-db-secret:auth-db:/run/cerberus/db',
            'keycloak-admin-secret:keycloak:/run/cerberus/admin', 'oidc-client-secret:api:/run/cerberus/client')) {
            $volume, $service, $target = $specification.Split(':')
            $container = Invoke-Compose -Arguments @('ps', '-aq', $service)
            if ($container -cnotmatch '^[a-f0-9]{12,64}$') { throw 'Contenedor persistente inválido.' }
            $template = '{{range .Mounts}}{{if eq .Destination "' + $target + '"}}{{.Name}}{{end}}{{end}}'
            $physical = Invoke-Docker -Arguments @('inspect', '--format', $template, $container)
            if ($physical -cnotmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]+$') { throw 'Volumen persistente inválido.' }
            $mounts += @('--volume', "${physical}:/run/cerberus-backup/${volume}:ro")
        }
        $apiContainer = Invoke-Compose -Arguments @('ps', '-aq', 'api')
        if ($apiContainer -cnotmatch '^[a-f0-9]{12,64}$') { throw 'Contenedor API inválido.' }
        Write-Host 'Creando backup privado completo; puede ocupar tanto como datos y modelos existentes.'
        Invoke-Docker -Arguments ($rootHelper + @('--volumes-from', "${apiContainer}:ro", '--volume', "${installation}:/release/current:ro", '--volume', "${backupPath}:/backup") + $mounts +
            @($helper, '-m', 'cerberus_api.release_state', '--operation', 'backup', '--current', '/release/current', '--backup', '/backup', '--helper-image', $helper, '--quiesced')) | Out-Null
        if ($mode -ne 'Backup') {
            $activated = $true
            Invoke-Docker -Arguments ($rootHelper + @('--volume', "${installation}:/release/current", '--volume', "${Candidate}:/release/candidate:ro", '--volume', "${backupPath}:/backup:ro",
                $helper, '-m', 'cerberus_api.release_state', '--operation', 'activate', '--current', '/release/current', '--candidate', '/release/candidate', '--backup', '/backup', '--quiesced')) | Out-Null
        }
        Invoke-Compose -Arguments @('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240') | Out-Null
        $paused = $false
        Write-Host 'Operación completada. Backup privado en .cerberus-backups; paquete previo en .cerberus-versions.'
    }
    $exitCode = 0
} catch {
    Write-Host 'Operación detenida. Conserva datos y backups; consulta docs/D3_UPDATE.md.'
} finally {
    if ($dumpCreated) { try { Invoke-Compose -Arguments @('exec', '-T', 'auth-db', 'rm', '-f', '/tmp/cerberus-update.dump') | Out-Null } catch { } }
    if ($exitCode -ne 0 -and $paused) {
        if (-not $activated) {
            try { Invoke-Compose -Arguments @('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '180') | Out-Null }
            catch { Write-Host 'La instalación anterior sigue detenida; inicia desde su carpeta cuando resuelvas el fallo.' }
        } else {
            try { Invoke-Compose -Arguments @('stop', 'frontend', 'api', 'worker') | Out-Null } catch { }
            Write-Host 'Aplicación detenida. Paquete previo y backup conservados; usa retorno explícito o restauración aislada.'
        }
    }
    if ($lock) {
        Remove-Item -LiteralPath (Join-Path $lock 'labels.json') -ErrorAction SilentlyContinue
        try { [System.IO.Directory]::Delete($lock) } catch { }
    }
    # También Ctrl+C debe devolver fallo después de liberar el lock propio.
    exit $exitCode
}
