param(
    [switch]$SkipInfrastructure,
    [switch]$NoBuild,
    [int]$TimeoutSeconds = 180,
    [string]$ComposeProjectName = ""
)

$ErrorActionPreference = "Stop"
if ($ComposeProjectName) {
    if ($ComposeProjectName -notmatch "^[a-z0-9][a-z0-9_-]+$") {
        throw "ComposeProjectName must contain only lowercase letters, digits, hyphens, and underscores"
    }
    $env:COMPOSE_PROJECT_NAME = $ComposeProjectName
}
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8000 }
$BackendBaseUrl = "http://127.0.0.1:$BackendPort"
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
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $raw = docker compose --profile paper-ibkr exec -T flink-jobmanager `
            curl -fsS http://127.0.0.1:8081/jobs/overview 2>$null
        $curlExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($curlExitCode -ne 0) {
        return @()
    }
    return @((ConvertFrom-Json $raw).jobs)
}

function Get-ExecutionReadiness {
    try {
        $response = Invoke-RestMethod "$BackendBaseUrl/api/v1/execution/readiness/"
    }
    catch {
        if (-not $_.ErrorDetails.Message) {
            throw
        }
        $response = ConvertFrom-Json $_.ErrorDetails.Message
    }
    if ($null -eq $response.data.ready -or $null -eq $response.data.signals) {
        throw "execution readiness response is missing ready/signals"
    }
    return $response.data
}

Push-Location $RepositoryRoot
try {
    if (-not $SkipInfrastructure) {
        if (-not $env:LOCAL_PAPER_GATEWAY_DJANGO_SECRET_KEY) {
            $env:LOCAL_PAPER_GATEWAY_DJANGO_SECRET_KEY = [guid]::NewGuid().ToString("N")
        }
        if (-not $env:LOCAL_PAPER_GATEWAY_SERVICE_TOKEN) {
            $env:LOCAL_PAPER_GATEWAY_SERVICE_TOKEN = [guid]::NewGuid().ToString("N")
        }
        if (-not $env:LOCAL_PAPER_GATEWAY_NOVNC_PASSWORD) {
            $env:LOCAL_PAPER_GATEWAY_NOVNC_PASSWORD = [guid]::NewGuid().ToString("N")
        }
    }
    elseif (-not $env:LOCAL_PAPER_GATEWAY_SERVICE_TOKEN) {
        throw "SkipInfrastructure requires LOCAL_PAPER_GATEWAY_SERVICE_TOKEN for the already-running paper Gateway"
    }

    Invoke-AutomaticExecutionStage "compose-config" {
        docker compose --profile paper-ibkr config --quiet
    }

    if (-not $SkipInfrastructure) {
        Invoke-AutomaticExecutionStage "infrastructure-start" {
            $arguments = @("compose", "--profile", "paper-ibkr", "up", "-d")
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
                "backend",
                "paper-ibkr-gateway"
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
                "backend",
                "paper-ibkr-gateway"
            )
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            do {
                $rows = @(docker compose --profile paper-ibkr ps --format json | ConvertFrom-Json)
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
                    $raw = docker compose --profile paper-ibkr exec -T flink-jobmanager curl -fsS "http://127.0.0.1:8081/jobs/$($job.jid)/checkpoints"
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
                $health = Invoke-RestMethod "$BackendBaseUrl/api/v1/streaming/health/"
                if ($health.data.consumer.status -eq "HEALTHY") {
                    break
                }
                Start-Sleep -Seconds 3
            } while ((Get-Date) -lt $deadline)
            if ($health.data.consumer.status -ne "HEALTHY") {
                throw "market consumer heartbeat is $($health.data.consumer.status)"
            }
        }

        Invoke-AutomaticExecutionStage "paper-gateway-reconciliation" {
            docker compose --profile paper-ibkr exec -T backend python manage.py sync_local_paper_gateway --reconcile
        }

        Invoke-AutomaticExecutionStage "retire-prior-smoke-strategies" {
            docker compose --profile paper-ibkr exec -T backend python manage.py retire_paper_smoke_strategies
        }

        Invoke-AutomaticExecutionStage "execution-readiness" {
            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            do {
                $readiness = Get-ExecutionReadiness
                if ($readiness.ready) {
                    break
                }
                Start-Sleep -Seconds 3
            } while ((Get-Date) -lt $deadline)
            if (-not $readiness.ready) {
                $codes = @($readiness.blockers | ForEach-Object code)
                throw "execution readiness is false: $($codes -join '; ')"
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
        docker compose --profile paper-ibkr exec -T backend mkdir -p /app/tests
        if ($LASTEXITCODE -ne 0) {
            throw "could not prepare the backend integration-test directory"
        }
        docker compose --profile paper-ibkr cp `
            Backend/tests/test_docker_paper_pipeline.py `
            backend:/app/tests/test_docker_paper_pipeline.py
        if ($LASTEXITCODE -ne 0) {
            throw "could not copy the paper-pipeline integration test into the backend container"
        }
        docker compose --profile paper-ibkr exec -T -e RUN_DOCKER_PAPER_PIPELINE=1 backend `
            pytest --ds=config.settings tests/test_docker_paper_pipeline.py -m docker_integration -q
    }

    Invoke-AutomaticExecutionStage "final-execution-readiness" {
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        do {
            $readiness = Get-ExecutionReadiness
            if ($readiness.ready) {
                break
            }
            Start-Sleep -Seconds 3
        } while ((Get-Date) -lt $deadline)
        if (-not $readiness.ready) {
            $codes = @($readiness.blockers | ForEach-Object code)
            throw "execution readiness is false after the pipeline test: $($codes -join '; ')"
        }
    }

    Write-Output "Automatic paper-execution smoke test passed"
}
finally {
    Pop-Location
}
