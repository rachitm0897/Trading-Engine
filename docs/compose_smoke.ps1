$ErrorActionPreference = "Stop"

docker compose config --quiet
docker compose up --build -d

$deadline = (Get-Date).AddMinutes(3)
do {
    $states = @(docker compose ps --format json | ConvertFrom-Json)
    $unhealthy = @($states | Where-Object { $_.Health -and $_.Health -ne "healthy" })
    if ($states.Count -eq 7 -and $unhealthy.Count -eq 0) { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)

if ($states.Count -ne 7 -or $unhealthy.Count -ne 0) { throw "Compose services did not become healthy" }

$null = Invoke-RestMethod "http://127.0.0.1:8000/healthz"
$null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5173/healthz"
$null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5173/dashboard"
$null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5173/ibkr-sessions"
$runtimeConfig = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5173/runtime-config.js").Content
if ($runtimeConfig -notmatch 'http://localhost:8000/api/v1') { throw "Frontend runtime Backend URL is incorrect" }
$accounts = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/accounts/"
if (@($accounts.data | Where-Object { $_.account_id -eq "DU-MOCK" }).Count) { throw "Demo broker account must not be created" }

try {
    Invoke-RestMethod "http://127.0.0.1:8000/api/v1/broker-sessions/" -Method Post -ContentType "application/json" -Body '{"display_name":"Unavailable locally","username":"unused","password":"unused","mode":"paper"}'
    throw "Managed broker-session creation unexpectedly succeeded without QCH"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 503) { throw }
}

$kafkaPorts = docker inspect finflock-trading-engine-kafka-1 --format '{{json .NetworkSettings.Ports}}'
$flinkPorts = docker inspect finflock-trading-engine-flink-jobmanager-1 --format '{{json .NetworkSettings.Ports}}'
if ($kafkaPorts -match 'HostPort' -or $flinkPorts -match 'HostPort') { throw "Kafka or Flink published a private listener" }

Write-Output "Compose smoke test passed"
