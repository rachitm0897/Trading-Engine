param(
    [switch]$SkipInfrastructure,
    [switch]$NoBuild,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$RequiredFlinkJobs = @(
    "market-normalization-v2",
    "bar-aggregation-v2",
    "indicator-computation-v2",
    "stale-price-detection-v1",
    "stream-health-v1"
)

function Invoke-AutomaticExecutionStage {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host "[automatic-execution:$Name] running"
    try {
        & $Action
        if ($LASTEXITCODE -notin @(0, $null)) {
            throw "command exited with code $LASTEXITCODE"
        }
        Write-Host "[automatic-execution:$Name] passed"
    }
    catch {
        throw "[automatic-execution:$Name] $($_.Exception.Message)"
    }
}

function Get-FlinkJobs {
    $raw = docker compose exec -T flink-jobmanager curl -fsS http://127.0.0.1:8081/jobs/overview
    if ($LASTEXITCODE -ne 0) {
        throw "Flink jobs endpoint failed"
    }
    return @((ConvertFrom-Json $raw).jobs)
}

Push-Location $RepositoryRoot
try {
    Invoke-AutomaticExecutionStage "compose-config" {
        docker compose config --quiet
    }

    if (-not $SkipInfrastructure) {
        Invoke-AutomaticExecutionStage "infrastructure-start" {
            $arguments = @("compose", "up", "-d")
            if (-not $NoBuild) {
                $arguments += "--build"
            }
            $arguments += @(
                "postgres",
                "redis",
                "kafka",
                "kafka-init",
                "flink-jobmanager",
                "flink-taskmanager",
                "backend"
            )
            docker @arguments
        }

        Invoke-AutomaticExecutionStage "service-health" {
            $required = @(
                "postgres",
                "redis",
                "kafka",
                "flink-jobmanager",
                "flink-taskmanager",
                "backend"
            )
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            do {
                $rows = @(docker compose ps --format json | ConvertFrom-Json)
                $missing = @($required | Where-Object { $_ -notin $rows.Service })
                $bad = @(
                    $rows |
                        Where-Object {
                            $_.Service -in $required -and (
                                $_.State -ne "running" -or
                                ($_.Health -and $_.Health -ne "healthy")
                            )
                        }
                )
                if ($missing.Count -eq 0 -and $bad.Count -eq 0) {
                    break
                }
                Start-Sleep -Seconds 3
            } while ((Get-Date) -lt $deadline)
            if ($missing.Count -or $bad.Count) {
                throw "services did not become healthy; missing=$($missing -join ',') unhealthy=$($bad.Service -join ',')"
            }
        }

        Invoke-AutomaticExecutionStage "flink-jobs" {
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            do {
                $jobs = @(Get-FlinkJobs)
                $actual = @($jobs | Where-Object state -eq "RUNNING" | ForEach-Object name)
                $missing = @($RequiredFlinkJobs | Where-Object { $_ -notin $actual })
                $unexpected = @($actual | Where-Object { $_ -notin $RequiredFlinkJobs })
                if ($missing.Count -eq 0 -and $unexpected.Count -eq 0) {
                    break
                }
                Start-Sleep -Seconds 3
            } while ((Get-Date) -lt $deadline)
            if ($missing.Count -or $unexpected.Count) {
                throw "required running job set differs; missing=$($missing -join ',') unexpected=$($unexpected -join ',')"
            }
        }

        Invoke-AutomaticExecutionStage "flink-checkpoints" {
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            do {
                $jobs = @(Get-FlinkJobs | Where-Object { $_.name -in $RequiredFlinkJobs })
                $missing = @()
                foreach ($job in $jobs) {
                    $raw = docker compose exec -T flink-jobmanager curl -fsS "http://127.0.0.1:8081/jobs/$($job.jid)/checkpoints"
                    $summary = ConvertFrom-Json $raw
                    if ([int]$summary.counts.completed -lt 1) {
                        $missing += $job.name
                    }
                }
                if ($jobs.Count -eq $RequiredFlinkJobs.Count -and $missing.Count -eq 0) {
                    break
                }
                Start-Sleep -Seconds 3
            } while ((Get-Date) -lt $deadline)
            if ($jobs.Count -ne $RequiredFlinkJobs.Count -or $missing.Count) {
                throw "completed checkpoint missing for: $($missing -join ',')"
            }
        }

        Invoke-AutomaticExecutionStage "backend-consumer" {
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            do {
                $health = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/streaming/health/"
                if ($health.data.consumer.status -eq "HEALTHY") {
                    break
                }
                Start-Sleep -Seconds 3
            } while ((Get-Date) -lt $deadline)
            if ($health.data.consumer.status -ne "HEALTHY") {
                throw "market consumer heartbeat is $($health.data.consumer.status)"
            }
        }

        Invoke-AutomaticExecutionStage "execution-readiness-report" {
            try {
                $response = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/execution/readiness/"
            }
            catch {
                if (-not $_.ErrorDetails.Message) {
                    throw
                }
                $response = ConvertFrom-Json $_.ErrorDetails.Message
            }
            $readiness = $response.data
            if ($null -eq $readiness.ready -or $null -eq $readiness.signals) {
                throw "execution readiness response is missing ready/signals"
            }
            if (-not $readiness.ready) {
                $codes = @($readiness.blockers | ForEach-Object code)
                Write-Host "Local execution is intentionally blocked: $($codes -join '; ')"
            }
        }
    }

    Invoke-AutomaticExecutionStage "architecture-contract" {
        if (-not (Test-Path $Python)) {
            throw "repository virtual environment is missing at $Python"
        }
        & $Python scripts\check_execution_architecture.py
    }

    Invoke-AutomaticExecutionStage "paper-pipeline" {
        $previousDatabaseUrl = $env:DATABASE_URL
        try {
            $env:DATABASE_URL = "sqlite:///:memory:"
            Push-Location (Join-Path $RepositoryRoot "Backend")
            try {
                & $Python -m pytest tests\test_automatic_execution_e2e.py -q
            }
            finally {
                Pop-Location
            }
        }
        finally {
            if ($null -eq $previousDatabaseUrl) {
                Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
            }
            else {
                $env:DATABASE_URL = $previousDatabaseUrl
            }
        }
    }

    Write-Output "Automatic paper-execution smoke test passed"
}
finally {
    Pop-Location
}
