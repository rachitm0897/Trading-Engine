$ErrorActionPreference = "Stop"

$expectedServices = @(
    "flink-jobmanager",
    "flink-taskmanager",
    "kafka",
    "kafka-init",
    "postgres",
    "redis"
) | Sort-Object

docker compose config --quiet
$configuredServices = @(docker compose config --services | Sort-Object)
if (Compare-Object $expectedServices $configuredServices) {
    throw "Compose contains an unexpected service set"
}

docker compose up -d

$expectedRunning = @("flink-jobmanager", "flink-taskmanager", "kafka", "postgres", "redis")
$deadline = (Get-Date).AddMinutes(5)
do {
    $running = @(docker compose ps --status running --services)
    $states = @(docker compose ps --format json | ConvertFrom-Json)
    $missing = @($expectedRunning | Where-Object { $_ -notin $running })
    $unhealthy = @($states | Where-Object { $_.Health -and $_.Health -ne "healthy" })
    if ($missing.Count -eq 0 -and $unhealthy.Count -eq 0) { break }
    Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)

if ($missing.Count -ne 0 -or $unhealthy.Count -ne 0) {
    throw "Infrastructure services did not become ready"
}

$kafkaInit = @(docker compose ps -a --format json kafka-init | ConvertFrom-Json)
if ($kafkaInit.Count -ne 1 -or $kafkaInit[0].State -ne "exited" -or $kafkaInit[0].ExitCode -ne 0) {
    throw "Kafka topic initialization did not complete successfully"
}

foreach ($service in @("redis", "kafka", "flink-jobmanager", "flink-taskmanager")) {
    $containerId = docker compose ps -q $service
    $ports = docker inspect $containerId --format '{{json .NetworkSettings.Ports}}'
    if ($ports -match 'HostPort') { throw "$service published a private listener" }
}

Write-Output "Infrastructure Compose smoke test passed"
