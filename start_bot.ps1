# start_bot.ps1 - bring the whole bot up: PostgreSQL (Docker) + cloudflared + uvicorn.
# Run from a terminal:
#   powershell -ExecutionPolicy Bypass -File D:\september\start_bot.ps1
#
# ORDER MATTERS: cloudflared runs FIRST so we learn the public URL, write it to .env,
# and only THEN start uvicorn. uvicorn reads .env once at startup (lru_cache), so if
# we start it before writing the URL it would keep the stale/dead audience in memory
# and card buttons would point to a dead tunnel.
#
# NOTE: cloudflared (quick tunnel) needs a network that can reach api.trycloudflare.com.
# If the log says "forcibly closed", the ISP is blocking it - turn on a VPN and re-run.

$ErrorActionPreference = "Stop"
$Root        = "D:\september"
$Python      = Join-Path $Root "venv\Scripts\python.exe"
$HealthUrl   = "http://127.0.0.1:8000/api/v1/health"
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$CloudLog    = Join-Path $Root "cloudflared.out.log"
$CloudErr    = Join-Path $Root "cloudflared.err.log"
$EnvFile     = Join-Path $Root ".env"

Write-Host "=== English Meet Bot - startup ==="

# 1. PostgreSQL - the project uses the Docker container `meet_bot_db` (host port 5433),
#    NOT the system PostgreSQL service. Bring it up automatically if it is stopped.
$dbUp = docker ps --filter "name=meet_bot_db" --format "{{.Names}}" 2>$null
if (-not $dbUp) {
    Write-Host "[..] DB container 'meet_bot_db' is stopped - starting it..."
    $exists = docker ps -a --filter "name=meet_bot_db" --format "{{.Names}}" 2>$null
    if ($exists) {
        docker start meet_bot_db 2>$null | Out-Null
        # give PostgreSQL a moment to accept connections
        Start-Sleep -Seconds 5
        Write-Host "[ok] DB container started"
    } else {
        Write-Host "[!!] Container 'meet_bot_db' not found." -ForegroundColor Red
        Write-Host "     Docker Desktop is probably not running. Start it, then run:" -ForegroundColor Red
        Write-Host "     docker compose up -d db" -ForegroundColor Red
    }
} else {
    Write-Host "[ok] PostgreSQL (docker: meet_bot_db) running"
}

# 2. Stop any stale uvicorn and cloudflared.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*uvicorn*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# 3. Start cloudflared quick tunnel FIRST: public trycloudflare.com URL -> :8000.
Start-Process -FilePath $Cloudflared `
    -ArgumentList 'tunnel','--url','http://localhost:8000','--no-autoupdate' `
    -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput $CloudLog `
    -RedirectStandardError  $CloudErr
Write-Host "[ok] cloudflared started"

# 4. Wait for the URL, then write it to .env BEFORE uvicorn starts.
Write-Host "[..] waiting ~10s for the tunnel URL..."
Start-Sleep -Seconds 10

$log = ""
if (Test-Path $CloudErr) { $log += (Get-Content $CloudErr -Raw) }
if (Test-Path $CloudLog) { $log += (Get-Content $CloudLog -Raw) }

if ($log -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
    $TunnelUrl = $Matches[0]
    Write-Host ("[ok] tunnel: {0}" -f $TunnelUrl) -ForegroundColor Green
    $audience = "$TunnelUrl/webhooks/google-chat"
    if (Test-Path $EnvFile) {
        $env = Get-Content $EnvFile
        $updated = $env -replace '^CHAT_APP_AUDIENCE=.*$', "CHAT_APP_AUDIENCE=$audience"
        Set-Content -Path $EnvFile -Value $updated -Encoding UTF8
        Write-Host "[ok] .env CHAT_APP_AUDIENCE -> $audience"
    }
} else {
    Write-Host "[!!] tunnel NOT assigned - check cloudflared.err.log." -ForegroundColor Red
    Write-Host "     If you see 'forcibly closed', the network blocks trycloudflare.com; enable VPN and re-run."
}

# 5. Now start uvicorn (reads the fresh CHAT_APP_AUDIENCE from .env).
Start-Process -FilePath $Python `
    -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' `
    -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Root "uvicorn.out.log") `
    -RedirectStandardError  (Join-Path $Root "uvicorn.err.log")
Write-Host "[ok] uvicorn started on :8000"

# 6. Wait for the app, then health-check.
Write-Host "[..] waiting ~8s and checking..."
Start-Sleep -Seconds 8

try {
    $h = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 8
    Write-Host ("[ok] bot: HTTP {0} -> {1}" -f $h.StatusCode, $h.Content) -ForegroundColor Green
} catch {
    Write-Host "[!!] bot NOT answering: $($_.Exception.Message)" -ForegroundColor Red
}

if ($TunnelUrl) {
    Write-Host "=== Done. Webhook: $audience ==="
    Write-Host "     Copy this URL into Google Cloud Console -> Chat App -> Webhook URL."
} else {
    Write-Host "=== Done (bot up locally, no public URL). ==="
}
