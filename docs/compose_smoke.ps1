$ErrorActionPreference = "Stop"

docker compose config --quiet
docker compose up --build -d

$deadline = (Get-Date).AddMinutes(3)
do {
    $states = docker compose ps --format json | ConvertFrom-Json
    $unhealthy = @($states | Where-Object { $_.Health -and $_.Health -ne "healthy" })
    if ($states.Count -eq 8 -and $unhealthy.Count -eq 0) { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)

if ($states.Count -ne 8 -or $unhealthy.Count -ne 0) { throw "Compose services did not become healthy" }

$null = Invoke-RestMethod "http://127.0.0.1:8000/healthz"
$null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5173/healthz"
$proxiedSystem = Invoke-RestMethod "http://127.0.0.1:5173/api/v1/system/"
if (-not $proxiedSystem.ok) { throw "Frontend same-origin API proxy failed" }
$null = Invoke-RestMethod "http://127.0.0.1:8080/healthz"
$accounts = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/accounts/"
if (@($accounts.data | Where-Object { $_.account_id -eq "DU-MOCK" }).Count) { throw "Demo broker account must not be created" }

try {
    Invoke-RestMethod "http://127.0.0.1:8080/api/v1/health/"
    throw "Gateway API accepted an unauthenticated request"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw }
}

$gatewayToken = $env:GATEWAY_SERVICE_TOKEN
if (-not $gatewayToken -and (Test-Path -LiteralPath ".env")) {
    $tokenLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -match '^GATEWAY_SERVICE_TOKEN=' } | Select-Object -First 1
    if ($tokenLine) { $gatewayToken = $tokenLine.Substring($tokenLine.IndexOf('=') + 1).Trim() }
}
if (-not $gatewayToken) { $gatewayToken = "local-service-token" }
$null = Invoke-RestMethod "http://127.0.0.1:8080/api/v1/health/" -Headers @{ Authorization = "Bearer $gatewayToken" }
$ports = docker inspect finflock-trading-engine-ib_gateway-1 --format '{{json .NetworkSettings.Ports}}'
if ($ports -match '4001|4002|5900|6080|8001') { throw "Gateway published a private listener" }
$kafkaPorts = docker inspect finflock-trading-engine-kafka-1 --format '{{json .NetworkSettings.Ports}}'
$flinkPorts = docker inspect finflock-trading-engine-flink-jobmanager-1 --format '{{json .NetworkSettings.Ports}}'
if ($kafkaPorts -match 'HostPort' -or $flinkPorts -match 'HostPort') { throw "Kafka or Flink published a private listener" }

Write-Output "Compose smoke test passed"
