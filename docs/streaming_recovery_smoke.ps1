$ErrorActionPreference = "Stop"

function Get-FlinkJobs {
    $raw = docker compose exec -T flink-jobmanager curl -fsS http://127.0.0.1:8081/jobs/overview
    return ($raw | ConvertFrom-Json).jobs
}

function Wait-FlinkHealthy {
    $deadline = (Get-Date).AddMinutes(2)
    do {
        try {
            $jobs = @(Get-FlinkJobs)
            if ($jobs.Count -eq 5 -and @($jobs | Where-Object { $_.state -ne "RUNNING" }).Count -eq 0) { return $jobs }
        } catch { }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    throw "Five Flink jobs did not recover to RUNNING"
}

function Wait-FlinkCheckpoints {
    param([array]$Jobs)
    $deadline = (Get-Date).AddMinutes(2)
    do {
        $ready = 0
        foreach ($job in $Jobs) {
            try {
                $raw = docker compose exec -T flink-jobmanager curl -fsS "http://127.0.0.1:8081/jobs/$($job.jid)/checkpoints"
                $summary = $raw | ConvertFrom-Json
                if ($summary.counts.completed -gt 0) { $ready++ }
            } catch { }
        }
        if ($ready -eq $Jobs.Count) { return }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    throw "All Flink jobs did not complete a durable checkpoint"
}

$before = @(Wait-FlinkHealthy)
docker compose restart flink-taskmanager
$afterTaskManager = @(Wait-FlinkHealthy)
Wait-FlinkCheckpoints -Jobs $afterTaskManager
docker compose restart flink-jobmanager
$afterJobManager = @(Wait-FlinkHealthy)

$expected = @("market-normalization-v1","bar-aggregation-v1","indicator-computation-v1","stale-price-detection-v1","stream-health-v1") | Sort-Object
if (Compare-Object $expected @($afterJobManager.name | Sort-Object)) { throw "Recovered Flink job set differs" }

Write-Output "Streaming recovery smoke test passed"
