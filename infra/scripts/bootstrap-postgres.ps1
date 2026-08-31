<#
.SYNOPSIS
    Brings up a local PostgreSQL 17 cluster with PostGIS and pgvector, on Windows,
    without Docker and without administrator rights.

.DESCRIPTION
    Everything lands under the repository:

        .tools/pgsql/     the merged PostgreSQL + PostGIS + pgvector binaries
        .tools/cache/     downloaded archives, kept so a re-run costs nothing
        var/pgdata/       the data directory
        var/pg.log        server log

    Both directories are git ignored. Nothing is written outside the repository and
    nothing is registered as a Windows service, so removing the two directories
    removes the database completely.

    The production target is the repository-owned image built by infra/Dockerfile.db,
    which infra/docker-compose.yml uses. That image is based on a digest-pinned official
    PostGIS image and adds a checksum-pinned pgvector package. This script exists because
    a Windows laptop without Docker Desktop or admin rights still has to be able to run
    the migrations and the spatial tests. The pgvector build is a third party Windows
    compilation, noted in docs/OPERATIONS.md, because pgvector ships no official Windows
    binary and building it needs the MSVC toolchain.

.PARAMETER Port
    Loopback port for the cluster. Defaults to 55432 to stay clear of a system install.

.PARAMETER Reset
    Delete the data directory and start from a fresh initdb. Destroys local data.

.EXAMPLE
    pwsh infra/scripts/bootstrap-postgres.ps1
    pwsh infra/scripts/bootstrap-postgres.ps1 -Reset
#>
[CmdletBinding()]
param(
    [int]$Port = 55432,
    [switch]$Reset,
    [string]$Database = 'auspice',
    [string]$User = 'auspice'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# --------------------------------------------------------------------------------
# Pinned versions. Bumping one of these is a deliberate act, so it happens here and
# nowhere else.
# --------------------------------------------------------------------------------
$PG_VERSION      = '17.9-1'
$POSTGIS_VERSION = '3.6.2'
$PGVECTOR_TAG    = '0.8.6_17'
$PGVECTOR_FILE   = 'vector.v0.8.6-pg17.zip'

$RepoRoot  = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot '..') '..')).Path
$ToolsDir  = Join-Path $RepoRoot '.tools'
$CacheDir  = Join-Path $ToolsDir 'cache'
$PgRoot    = Join-Path $ToolsDir 'pgsql'
$PgBin     = Join-Path $PgRoot 'bin'
$VarDir    = Join-Path $RepoRoot 'var'
$DataDir   = Join-Path $VarDir 'pgdata'
$LogFile   = Join-Path $VarDir 'pg.log'
$PwFile    = Join-Path $VarDir 'pg.superuser.pw'

function Write-Step   { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Detail { param([string]$m) Write-Host "    $m" -ForegroundColor DarkGray }
function Write-Ok     { param([string]$m) Write-Host "    $m" -ForegroundColor Green }

function Get-Archive {
    param([string]$Url, [string]$OutFile)
    if (Test-Path $OutFile) {
        Write-Detail "cached  $(Split-Path $OutFile -Leaf)"
        return
    }
    Write-Detail "fetch   $Url"
    $tmp = "$OutFile.partial"
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -MaximumRedirection 10
    Move-Item -Force $tmp $OutFile
    $mb = [math]::Round((Get-Item $OutFile).Length / 1MB, 1)
    Write-Ok "got     $(Split-Path $OutFile -Leaf) ($mb MB)"
}

function Copy-Tree {
    # Merge a source tree into a destination tree, overwriting file by file.
    param([string]$Source, [string]$Destination)
    Get-ChildItem -Path $Source -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart('\', '/')
        $target = Join-Path $Destination $relative
        $parent = Split-Path $target -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item -Force $_.FullName $target
    }
}

# --------------------------------------------------------------------------------
# 1. Binaries
# --------------------------------------------------------------------------------
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
New-Item -ItemType Directory -Path $VarDir   -Force | Out-Null

if (-not (Test-Path (Join-Path $PgBin 'postgres.exe'))) {
    Write-Step "Installing PostgreSQL $PG_VERSION, PostGIS $POSTGIS_VERSION, pgvector $PGVECTOR_TAG"

    $pgZip       = Join-Path $CacheDir "postgresql-$PG_VERSION-windows-x64-binaries.zip"
    $postgisZip  = Join-Path $CacheDir "postgis-bundle-pg17-${POSTGIS_VERSION}x64.zip"
    $pgvectorZip = Join-Path $CacheDir $PGVECTOR_FILE

    Get-Archive "https://get.enterprisedb.com/postgresql/postgresql-$PG_VERSION-windows-x64-binaries.zip" $pgZip
    Get-Archive "https://download.osgeo.org/postgis/windows/pg17/postgis-bundle-pg17-${POSTGIS_VERSION}x64.zip" $postgisZip
    Get-Archive "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/$PGVECTOR_TAG/$PGVECTOR_FILE" $pgvectorZip

    $staging = Join-Path $ToolsDir 'staging'
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    New-Item -ItemType Directory -Path $staging -Force | Out-Null

    Write-Detail 'expand  postgresql'
    Expand-Archive -Path $pgZip -DestinationPath $staging -Force
    if (Test-Path $PgRoot) { Remove-Item -Recurse -Force $PgRoot }
    Move-Item (Join-Path $staging 'pgsql') $PgRoot

    Write-Detail 'expand  postgis bundle'
    $postgisStage = Join-Path $staging 'postgis'
    Expand-Archive -Path $postgisZip -DestinationPath $postgisStage -Force
    # The bundle wraps everything in a single versioned directory.
    $inner = Get-ChildItem $postgisStage -Directory | Select-Object -First 1
    $postgisSource = if ($inner -and -not (Test-Path (Join-Path $postgisStage 'bin'))) { $inner.FullName } else { $postgisStage }
    Copy-Tree -Source $postgisSource -Destination $PgRoot

    Write-Detail 'expand  pgvector'
    $vectorStage = Join-Path $staging 'pgvector'
    Expand-Archive -Path $pgvectorZip -DestinationPath $vectorStage -Force
    $vInner = Get-ChildItem $vectorStage -Directory | Select-Object -First 1
    $vectorSource = if ($vInner -and -not (Test-Path (Join-Path $vectorStage 'lib'))) { $vInner.FullName } else { $vectorStage }
    Copy-Tree -Source $vectorSource -Destination $PgRoot

    Remove-Item -Recurse -Force $staging
    Write-Ok "binaries at $PgRoot"
} else {
    Write-Step 'Binaries already present'
    Write-Detail $PgRoot
}

$env:Path = "$PgBin;$env:Path"

# --------------------------------------------------------------------------------
# 2. Cluster
# --------------------------------------------------------------------------------
if ($Reset -and (Test-Path $DataDir)) {
    Write-Step 'Resetting the cluster'
    & (Join-Path $PgBin 'pg_ctl.exe') -D $DataDir -m immediate stop 2>$null | Out-Null
    Start-Sleep -Milliseconds 500
    Remove-Item -Recurse -Force $DataDir
}

if (-not (Test-Path (Join-Path $DataDir 'PG_VERSION'))) {
    Write-Step 'Initialising the cluster'

    # A real password, generated once, kept out of git, readable only through var/.
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'x').Replace('/', 'y')
    Set-Content -Path $PwFile -Value $password -NoNewline -Encoding ascii

    & (Join-Path $PgBin 'initdb.exe') `
        --pgdata=$DataDir `
        --username=postgres `
        --pwfile=$PwFile `
        --auth-host=scram-sha-256 `
        --auth-local=scram-sha-256 `
        --encoding=UTF8 `
        --locale=C `
        --data-checksums | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "initdb failed with exit code $LASTEXITCODE" }

    # Loopback only. This cluster is never reachable from the network.
    $conf = Join-Path $DataDir 'postgresql.conf'
    Add-Content -Path $conf -Value @"

# ---- Auspice local development overrides -------------------------------------
listen_addresses = '127.0.0.1'
port = $Port
max_connections = 100
shared_buffers = '512MB'
work_mem = '32MB'
maintenance_work_mem = '256MB'
effective_cache_size = '4GB'
random_page_cost = 1.1
timezone = 'UTC'
log_timezone = 'UTC'
datestyle = 'iso, mdy'
log_min_duration_statement = 500
"@
    Write-Ok 'cluster initialised'
} else {
    Write-Step 'Cluster already initialised'
    Write-Detail $DataDir
}

# --------------------------------------------------------------------------------
# 3. Start
# --------------------------------------------------------------------------------
& (Join-Path $PgBin 'pg_ctl.exe') -D $DataDir status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Starting PostgreSQL on 127.0.0.1:$Port"
    & (Join-Path $PgBin 'pg_ctl.exe') -D $DataDir -l $LogFile -o "-p $Port" -w start
    if ($LASTEXITCODE -ne 0) {
        Write-Host (Get-Content $LogFile -Tail 40 -ErrorAction SilentlyContinue) -ForegroundColor Red
        throw "pg_ctl start failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Step "PostgreSQL already running on port $Port"
}

# --------------------------------------------------------------------------------
# 4. Role, database, extensions
# --------------------------------------------------------------------------------
$superPassword = (Get-Content $PwFile -Raw).Trim()
$env:PGPASSWORD = $superPassword
$psql = Join-Path $PgBin 'psql.exe'
$base = @('-h', '127.0.0.1', '-p', $Port, '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-q', '-t', '-A')

function Invoke-Psql {
    param([string]$Sql, [string]$Db = 'postgres')
    $out = & $psql @base '-d' $Db '-c' $Sql 2>&1
    if ($LASTEXITCODE -ne 0) { throw "psql failed: $out" }
    return ($out | Out-String).Trim()
}

Write-Step 'Provisioning role and database'

# The application role owns the schema. It is not a superuser: the migrations must
# work under the same privileges production has.
$roleExists = Invoke-Psql "SELECT 1 FROM pg_roles WHERE rolname = '$User'"
if (-not $roleExists) {
    Invoke-Psql "CREATE ROLE $User LOGIN PASSWORD '$superPassword' CREATEDB" | Out-Null
    Write-Ok "role $User created"
} else {
    Invoke-Psql "ALTER ROLE $User LOGIN PASSWORD '$superPassword'" | Out-Null
    Write-Detail "role $User already present"
}

$dbExists = Invoke-Psql "SELECT 1 FROM pg_database WHERE datname = '$Database'"
if (-not $dbExists) {
    Invoke-Psql "CREATE DATABASE $Database OWNER $User ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'" | Out-Null
    Write-Ok "database $Database created"
} else {
    Write-Detail "database $Database already present"
}

$testDb = "${Database}_test"
$testExists = Invoke-Psql "SELECT 1 FROM pg_database WHERE datname = '$testDb'"
if (-not $testExists) {
    Invoke-Psql "CREATE DATABASE $testDb OWNER $User ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'" | Out-Null
    Write-Ok "database $testDb created"
}

# Extensions need superuser, so they are created here rather than in a migration.
# The migration asserts they exist and fails loudly if they do not.
Write-Step 'Enabling extensions'
foreach ($db in @($Database, $testDb)) {
    foreach ($ext in @('postgis', 'pg_trgm', 'vector', 'btree_gist')) {
        try {
            Invoke-Psql "CREATE EXTENSION IF NOT EXISTS $ext" $db | Out-Null
            Write-Ok "$db : $ext"
        } catch {
            Write-Host "    $db : $ext  FAILED" -ForegroundColor Red
            Write-Host "      $($_.Exception.Message)" -ForegroundColor Red
            throw
        }
    }
}

$versions = Invoke-Psql "SELECT extname || ' ' || extversion FROM pg_extension ORDER BY extname" $Database

# --------------------------------------------------------------------------------
# 5. Report the connection string
# --------------------------------------------------------------------------------
$dsn     = "postgresql+psycopg://${User}:${superPassword}@127.0.0.1:$Port/$Database"
$testDsn = "postgresql+psycopg://${User}:${superPassword}@127.0.0.1:$Port/$testDb"

$envPath = Join-Path $RepoRoot '.env'
$lines = @()
if (Test-Path $envPath) {
    $lines = Get-Content $envPath | Where-Object { $_ -notmatch '^AUSPICE_DATABASE_URL=' -and $_ -notmatch '^AUSPICE_TEST_DATABASE_URL=' }
}
$lines += "AUSPICE_DATABASE_URL=$dsn"
$lines += "AUSPICE_TEST_DATABASE_URL=$testDsn"
Set-Content -Path $envPath -Value $lines -Encoding utf8

Write-Host ''
Write-Step 'Ready'
Write-Host $versions -ForegroundColor DarkGray
Write-Host ''
Write-Detail "server     127.0.0.1:$Port"
Write-Detail "data       $DataDir"
Write-Detail "log        $LogFile"
Write-Detail "connection written to .env as AUSPICE_DATABASE_URL"
Write-Host ''
Write-Detail 'stop with:  .tools\pgsql\bin\pg_ctl.exe -D var\pgdata stop'
Write-Host ''
