$ErrorActionPreference = "Stop"

docker compose config --quiet
docker compose up --build -d

$deadline = (Get-Date).AddMinutes(3)
do {
    $states = docker compose ps --format json | ConvertFrom-Json
    $unhealthy = @($states | Where-Object { $_.Health -and $_.Health -ne "healthy" })
    if ($states.Count -eq 5 -and $unhealthy.Count -eq 0) { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)

if ($states.Count -ne 5 -or $unhealthy.Count -ne 0) { throw "Compose services did not become healthy" }

$null = Invoke-RestMethod "http://127.0.0.1:8000/healthz"
$null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5173/healthz"
$null = Invoke-RestMethod "http://127.0.0.1:8080/healthz"
$strategies = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/strategies/"
if ($strategies.data.Count -ne 5) { throw "Expected exactly five strategy definitions" }

try {
    Invoke-RestMethod "http://127.0.0.1:8080/api/v1/health/"
    throw "Gateway API accepted an unauthenticated request"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw }
}

$null = Invoke-RestMethod "http://127.0.0.1:8080/api/v1/health/" -Headers @{ Authorization = "Bearer local-service-token" }
$ports = docker inspect finflock-trading-engine-ib_gateway-1 --format '{{json .NetworkSettings.Ports}}'
if ($ports -match '4001|4002|5900|6080|8001') { throw "Gateway published a private listener" }

Write-Output "Compose smoke test passed"
