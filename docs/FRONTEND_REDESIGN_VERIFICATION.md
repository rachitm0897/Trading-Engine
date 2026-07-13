# Frontend redesign verification

This file records the untouched baseline and final verification for the frontend-first redesign.

## Baseline (2026-07-13)

Executed before implementation from a clean tracked worktree (the pre-existing untracked implementation plan was left untouched):

| Check | Result |
|---|---|
| `cd Backend && ..\.venv\Scripts\python.exe -m pytest` | 49 passed in 7.36s |
| `cd IB_gateway && ..\.venv\Scripts\python.exe -m pytest` | 10 passed in 0.24s |
| `cd Frontend && npm test` | 5 passed in 5.98s |
| `cd Frontend && npm run build` | Passed; 1,578 modules transformed in 316ms |
| `.\.venv\Scripts\python.exe -m pytest streaming/flink/tests` | 3 passed in 0.06s |
| `docker compose config --quiet` | Passed |

## Final verification

Executed after implementation on 2026-07-13:

| Check | Result |
|---|---|
| `cd Backend && ..\.venv\Scripts\python.exe -m pytest` | 53 passed in 8.78s |
| `cd IB_gateway && ..\.venv\Scripts\python.exe -m pytest` | 10 passed in 0.33s |
| `cd Frontend && npm test` | 3 files and 11 tests passed in 7.48s |
| `cd Frontend && npm run build` | Passed; 1,661 modules transformed, 472.68 kB JS (145.86 kB gzip), built in 481ms |
| `.\.venv\Scripts\python.exe -m pytest streaming/flink/tests` | 3 passed in 0.07s |
| `docker compose config --quiet` | Passed |
| `powershell -NoProfile -File docs/compose_smoke.ps1` | Passed; images built, eight services healthy, public health and same-origin proxy checks passed, Gateway authentication enforced, and no private Gateway/Kafka/Flink listeners published |
| `powershell -NoProfile -File docs/streaming_recovery_smoke.ps1` | Passed in 82.3s; TaskManager and JobManager restarted and all five jobs recovered |

The first Compose smoke attempt encountered a transient Docker container-name conflict during recreation. Running `docker compose up -d` allowed the interrupted recreation to converge without deleting volumes; the canonical smoke script then passed. The first recovery run exposed an obsolete assertion for the `bar-aggregation-v1` and `indicator-computation-v1` names. Those jobs are versioned `v2` in source, so the script expectation was corrected and the complete recovery run passed.
