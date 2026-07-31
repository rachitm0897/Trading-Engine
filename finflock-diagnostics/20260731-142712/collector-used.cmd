@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PROJECT=finflock-real-paper-test"
set "DC=docker compose -p %PROJECT% --env-file .env -f docker-compose.yml -f docker-compose.real-paper.yml --profile paper-ibkr"

for %%F in (.env docker-compose.yml docker-compose.real-paper.yml finflock_backend_snapshot.py finflock_gateway_snapshot.py redact_finflock_diagnostics.py) do (
  if not exist "%%F" echo ERROR: Missing %%F & if not exist "%%F" exit /b 1
)
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%I"
set "OUT=finflock-diagnostics\%TS%"
set "ZIP=finflock-diagnostics-%TS%.zip"
mkdir "%OUT%" 2>nul

echo Collecting diagnostics into %OUT% ...
(
 echo CapturedAt=%DATE% %TIME%
 echo WorkingDirectory=%CD%
 echo ComposeProject=%PROJECT%
 echo ==== GIT HEAD ====
 git rev-parse HEAD 2^>^&1
 echo ==== GIT BRANCH ====
 git branch --show-current 2^>^&1
 echo ==== GIT STATUS ====
 git status --short 2^>^&1
 echo ==== DOCKER ====
 docker version 2^>^&1
 docker compose version 2^>^&1
) > "%OUT%\00-host-and-git.txt" 2>&1

%DC% config --services > "%OUT%\01-compose-services.txt" 2>&1
%DC% config --profiles > "%OUT%\02-compose-profiles.txt" 2>&1
%DC% ps -a > "%OUT%\03-compose-ps.txt" 2>&1
%DC% images > "%OUT%\04-compose-images.txt" 2>&1
netstat -ano > "%OUT%\05-host-netstat.txt" 2>&1

for %%S in (postgres redis kafka kafka-init flink-jobmanager flink-taskmanager backend frontend paper-ibkr-gateway) do (
 echo Collecting %%S logs...
 %DC% logs --no-color --timestamps --tail 10000 %%S > "%OUT%\docker-logs-%%S.txt" 2>&1
 for /f "delims=" %%C in ('%DC% ps -q %%S 2^>nul') do docker inspect --format "Name={{.Name}} Image={{.Config.Image}} State={{.State.Status}} Running={{.State.Running}} ExitCode={{.State.ExitCode}} StartedAt={{.State.StartedAt}} Health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} Ports={{json .NetworkSettings.Ports}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}}={{$v.IPAddress}} {{end}}" %%C > "%OUT%\docker-inspect-safe-%%S.txt" 2>&1
)

echo Collecting Backend and Frontend HTTP state...
for %%U in (
 "healthz|http-backend-healthz"
 "readyz|http-backend-readyz"
 "api/v1/system/|http-backend-system"
 "api/v1/execution/readiness/|http-execution-readiness"
 "api/v1/execution/diagnostics/|http-execution-diagnostics"
 "api/v1/streaming/health/|http-streaming-health"
 "api/v1/data-providers/finnhub/|http-finnhub-status"
 "api/v1/research/readiness/|http-candidate-research-readiness"
 "api/v1/portfolio-construction/readiness/|http-candidate-portfolio-construction-readiness"
 "api/v1/portfolio-builder/readiness/|http-candidate-portfolio-builder-readiness"
 "api/v1/recommendations/readiness/|http-candidate-recommendations-readiness"
) do for /f "tokens=1,2 delims=|" %%A in ("%%~U") do curl.exe -sS -i --max-time 20 "http://localhost:8000/%%A" > "%OUT%\%%B.txt" 2>&1
curl.exe -sS -i --max-time 15 http://localhost:5173/healthz > "%OUT%\http-frontend-healthz.txt" 2>&1
curl.exe -sS -i --max-time 15 http://localhost:5173/runtime-config.js > "%OUT%\http-frontend-runtime-config.txt" 2>&1

echo Collecting noVNC and Gateway state...
curl.exe -sS -i --max-time 15 http://localhost:8082/healthz > "%OUT%\http-gateway-healthz.txt" 2>&1
curl.exe -sS -i --max-time 15 http://localhost:8082/readyz > "%OUT%\http-gateway-readyz.txt" 2>&1
curl.exe -v --max-time 15 "http://localhost:8082/novnc/vnc.html?autoconnect=true&resize=scale&path=novnc/websockify" > "%OUT%\http-novnc-vnc-page-body.html" 2> "%OUT%\http-novnc-vnc-page-verbose.txt"
curl.exe --http1.1 -i -N --max-time 5 -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" http://localhost:8082/novnc/websockify > "%OUT%\http-novnc-websocket-handshake.txt" 2>&1
%DC% port paper-ibkr-gateway 8080 > "%OUT%\gateway-compose-port.txt" 2>&1
%DC% exec -T paper-ibkr-gateway supervisorctl status > "%OUT%\gateway-supervisor-status.txt" 2>&1
%DC% exec -T paper-ibkr-gateway sh -lc "echo ====PROCESSES====; ps aux; echo ====FILES====; ls -la /tmp/.X11-unix /home/ibgateway/.vnc /home/ibgateway/ibc 2>&1; echo ====INTERNAL_HTTP====; curl -sS -i --max-time 5 http://127.0.0.1:6080/vnc.html; echo; curl -sS -i --max-time 5 http://127.0.0.1:8001/healthz" > "%OUT%\gateway-process-and-internal-services.txt" 2>&1
%DC% exec -T paper-ibkr-gateway python - < finflock_gateway_snapshot.py > "%OUT%\gateway-api-and-socket-snapshot.txt" 2>&1

echo Collecting Backend process, queue, and database snapshots...
%DC% exec -T backend python manage.py check > "%OUT%\backend-django-check.txt" 2>&1
%DC% exec -T backend python manage.py showmigrations --plan > "%OUT%\backend-migrations.txt" 2>&1
%DC% exec -T backend supervisorctl status > "%OUT%\backend-supervisor-status.txt" 2>&1
for %%I in (ping stats active reserved scheduled active_queues) do %DC% exec -T backend celery -A config inspect %%I --timeout=10 > "%OUT%\celery-%%I.txt" 2>&1
%DC% exec -T backend python manage.py shell < finflock_backend_snapshot.py > "%OUT%\backend-database-snapshot.txt" 2>&1

echo Collecting infrastructure state...
%DC% exec -T postgres pg_isready -U trading -d trading_engine > "%OUT%\postgres-readiness.txt" 2>&1
%DC% exec -T redis redis-cli ping > "%OUT%\redis-ping.txt" 2>&1
%DC% exec -T redis redis-cli info server > "%OUT%\redis-server-info.txt" 2>&1
%DC% exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list > "%OUT%\kafka-topics.txt" 2>&1
%DC% exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --list > "%OUT%\kafka-consumer-groups.txt" 2>&1
type nul > "%OUT%\kafka-consumer-group-details.txt"
for /f "usebackq delims=" %%G in ("%OUT%\kafka-consumer-groups.txt") do (
 echo ==== %%G ====>> "%OUT%\kafka-consumer-group-details.txt"
 %DC% exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group "%%G" >> "%OUT%\kafka-consumer-group-details.txt" 2>&1
)
%DC% exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server kafka:9092 > "%OUT%\kafka-topic-offsets.txt" 2>&1
curl.exe -sS -i --max-time 15 http://localhost:8081/overview > "%OUT%\flink-overview.txt" 2>&1
curl.exe -sS -i --max-time 15 http://localhost:8081/jobs/overview > "%OUT%\flink-jobs-overview.txt" 2>&1
curl.exe -sS -i --max-time 15 http://localhost:8081/taskmanagers > "%OUT%\flink-taskmanagers.txt" 2>&1
powershell -NoProfile -Command "$ErrorActionPreference='Continue'; $out='%OUT%\flink-job-details.txt'; try {$jobs=(Invoke-RestMethod 'http://localhost:8081/jobs/overview').jobs; foreach($j in $jobs) {'==== '+$j.name+' '+$j.jid+' ====' | Out-File $out -Append; Invoke-RestMethod ('http://localhost:8081/jobs/'+$j.jid) | ConvertTo-Json -Depth 12 | Out-File $out -Append; Invoke-RestMethod ('http://localhost:8081/jobs/'+$j.jid+'/checkpoints') | ConvertTo-Json -Depth 12 | Out-File $out -Append}} catch {$_ | Out-File $out -Append}" > "%OUT%\flink-detail-collector-console.txt" 2>&1

copy /Y "%~f0" "%OUT%\collector-used.cmd" >nul
copy /Y finflock_backend_snapshot.py "%OUT%\finflock_backend_snapshot.py" >nul
copy /Y finflock_gateway_snapshot.py "%OUT%\finflock_gateway_snapshot.py" >nul
copy /Y redact_finflock_diagnostics.py "%OUT%\redact_finflock_diagnostics.py" >nul

where py >nul 2>nul
if %ERRORLEVEL%==0 (py redact_finflock_diagnostics.py .env "%OUT%" > "%OUT%\redaction-report.txt" 2>&1) else (python redact_finflock_diagnostics.py .env "%OUT%" > "%OUT%\redaction-report.txt" 2>&1)
tar.exe -a -c -f "%ZIP%" -C "%OUT%" .

echo.
echo COMPLETE: %CD%\%ZIP%
echo Review the ZIP before uploading. It excludes full Docker environments and redacts exact values from sensitive .env variables.
endlocal
