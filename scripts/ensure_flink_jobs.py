#!/usr/bin/env python3
"""Ensure the required PyFlink jobs are running in the external cluster."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

import psycopg
import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

LOGGER = logging.getLogger("flink-job-bootstrap")

DEFAULT_REQUIRED_JOBS = (
    "market-normalization-v2",
    "bar-aggregation-v2",
    "indicator-computation-v2",
    "stale-price-detection-v1",
    "stream-health-v1",
)

JOB_FILES = {
    "market-normalization-v2": "market_normalization.py",
    "bar-aggregation-v2": "bar_aggregation.py",
    "indicator-computation-v2": "indicator_computation.py",
    "stale-price-detection-v1": "stale_price_detection.py",
    "stream-health-v1": "stream_health.py",
}

# These are the Flink states for which another copy can be started deliberately.
# Every unrecognized state is handled conservatively as non-terminal.
TERMINAL_STATES = frozenset({"FAILED", "CANCELED", "FINISHED", "SUSPENDED"})
RUNNING_STATE = "RUNNING"
ADVISORY_LOCK_KEY = 0x464C494E4B4A4F42  # ASCII "FLINKJOB"
JOB_ID_PATTERN = re.compile(r"\bJobID\s+([0-9a-fA-F]{32})\b")
KAFKA_CONNECTOR_JAR = Path(
    "/opt/flink/lib/flink-sql-connector-kafka-3.3.0-1.20.jar"
)


class BootstrapError(RuntimeError):
    """A safe-to-log Flink bootstrap failure."""


class ConfigurationError(BootstrapError):
    pass


class FlinkUnavailable(BootstrapError):
    pass


class JobTerminalError(BootstrapError):
    pass


@dataclass(frozen=True)
class Job:
    job_id: str
    name: str
    state: str


@dataclass(frozen=True)
class CompletedCheckpoint:
    checkpoint_id: int
    external_path: str
    completed_at_millis: int


@dataclass(frozen=True)
class SubmissionDecision:
    action: str
    job: Job | None
    matches: tuple[Job, ...]


@dataclass(frozen=True)
class BootstrapConfig:
    enabled: bool
    rest_url: str
    cli_jobmanager: str
    required_jobs: tuple[str, ...]
    files_root: Path
    flink_binary: str
    python_client_executable: str
    kafka_connector_jar: Path
    database_url: str
    submission_timeout_seconds: float
    start_timeout_seconds: float
    poll_interval_seconds: float
    max_attempts: int
    rest_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "BootstrapConfig":
        rest_url, cli_jobmanager = _parse_rest_url(
            os.getenv("FLINK_REST_URL", "http://localhost:8081")
        )
        required_jobs = _required_jobs(
            os.getenv("EXECUTION_REQUIRED_FLINK_JOBS", "")
        )
        submission_timeout = _positive_float(
            "FLINK_JOB_SUBMISSION_TIMEOUT_SECONDS", 60
        )
        start_timeout = _positive_float("FLINK_JOB_START_TIMEOUT_SECONDS", 120)
        poll_interval = _positive_float("FLINK_JOB_POLL_INTERVAL_SECONDS", 2)
        max_attempts = _positive_integer("FLINK_JOB_BOOTSTRAP_MAX_ATTEMPTS", 30)
        configured_binary = os.getenv("FLINK_BIN", "").strip()
        flink_binary = configured_binary or shutil.which("flink") or "/opt/flink/bin/flink"
        return cls(
            enabled=_environment_bool("FLINK_AUTO_SUBMIT_JOBS", True),
            rest_url=rest_url,
            cli_jobmanager=cli_jobmanager,
            required_jobs=required_jobs,
            files_root=Path(
                os.getenv("FLINK_JOB_FILES_ROOT", "/app/streaming/flink/jobs")
            ).expanduser(),
            flink_binary=flink_binary,
            python_client_executable=os.getenv(
                "PYFLINK_CLIENT_EXECUTABLE",
                "/opt/pyflink-venv/bin/python",
            ).strip(),
            kafka_connector_jar=KAFKA_CONNECTOR_JAR,
            database_url=os.getenv("DATABASE_URL", "").strip(),
            submission_timeout_seconds=submission_timeout,
            start_timeout_seconds=start_timeout,
            poll_interval_seconds=poll_interval,
            max_attempts=max_attempts,
            rest_timeout_seconds=min(submission_timeout, 10.0),
        )

    def validate(self) -> None:
        if not self.database_url:
            raise ConfigurationError(
                "DATABASE_URL is required for the distributed Flink bootstrap lock"
            )
        if len(set(self.required_jobs)) != len(self.required_jobs):
            raise ConfigurationError(
                "EXECUTION_REQUIRED_FLINK_JOBS contains duplicate names"
            )
        unknown = [name for name in self.required_jobs if name not in JOB_FILES]
        if unknown:
            raise ConfigurationError(
                "No Flink source mapping exists for configured job(s): "
                + ", ".join(unknown)
            )
        missing = [
            str(self.files_root / JOB_FILES[name])
            for name in self.required_jobs
            if not (self.files_root / JOB_FILES[name]).is_file()
        ]
        if missing:
            raise ConfigurationError(
                "Flink source file(s) are missing: " + ", ".join(missing)
            )
        if not Path(self.flink_binary).is_file() and shutil.which(self.flink_binary) is None:
            raise ConfigurationError(
                f"Flink CLI executable was not found at '{self.flink_binary}'"
            )
        if not Path(self.python_client_executable).is_file():
            raise ConfigurationError(
                "PyFlink client Python executable was not found at "
                f"'{self.python_client_executable}'"
            )
        if not self.kafka_connector_jar.is_file():
            raise ConfigurationError(
                "Flink Kafka connector JAR was not found at "
                f"'{self.kafka_connector_jar}'"
            )


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _positive_integer(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < 1:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


def _required_jobs(configured: str) -> tuple[str, ...]:
    if not configured.strip():
        return DEFAULT_REQUIRED_JOBS
    jobs = tuple(name.strip() for name in configured.split(",") if name.strip())
    if not jobs:
        raise ConfigurationError("EXECUTION_REQUIRED_FLINK_JOBS is empty")
    return jobs


def _parse_rest_url(value: str) -> tuple[str, str]:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError(
            "FLINK_REST_URL must be an http:// or https:// endpoint"
        )
    if parsed.username or parsed.password:
        raise ConfigurationError("FLINK_REST_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("FLINK_REST_URL must not contain a query or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("FLINK_REST_URL contains an invalid port") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    return normalized, f"{host}:{port}"


class FlinkRestClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def _get_json(self, path: str, *, allow_not_found: bool = False):
        try:
            response = self.session.get(
                self.base_url + path,
                timeout=self.timeout_seconds,
            )
            if allow_not_found and response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise FlinkUnavailable("Flink REST request timed out") from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            suffix = f" (HTTP {status})" if status is not None else ""
            raise FlinkUnavailable(
                f"Flink REST request failed with {type(exc).__name__}{suffix}"
            ) from exc
        except ValueError as exc:
            raise FlinkUnavailable("Flink REST returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise FlinkUnavailable("Flink REST returned an unexpected payload")
        return payload

    def list_jobs(self) -> list[Job]:
        payload = self._get_json("/jobs/overview")
        jobs = []
        for item in payload.get("jobs") or []:
            if not isinstance(item, Mapping):
                continue
            job_id = str(item.get("jid") or item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            state = str(item.get("state") or "UNKNOWN").strip().upper()
            if job_id and name:
                jobs.append(Job(job_id=job_id, name=name, state=state))
        return jobs

    def get_job(self, job_id: str) -> Job | None:
        payload = self._get_json(f"/jobs/{job_id}", allow_not_found=True)
        if payload is None:
            return None
        resolved_id = str(payload.get("jid") or payload.get("id") or job_id).strip()
        name = str(payload.get("name") or "").strip()
        state = str(payload.get("state") or "UNKNOWN").strip().upper()
        if not name:
            raise FlinkUnavailable(
                f"Flink REST returned no name for submitted job ID {job_id}"
            )
        return Job(job_id=resolved_id, name=name, state=state)

    def latest_completed_checkpoint(self, job_id: str) -> CompletedCheckpoint | None:
        payload = self._get_json(
            f"/jobs/{job_id}/checkpoints",
            allow_not_found=True,
        )
        if payload is None:
            return None
        latest = (payload.get("latest") or {}).get("completed")
        candidates = [latest] if isinstance(latest, Mapping) else []
        candidates.extend(
            item
            for item in (payload.get("history") or [])
            if isinstance(item, Mapping)
            and str(item.get("status") or "").upper() == "COMPLETED"
        )
        checkpoints = []
        for item in candidates:
            external_path = str(item.get("external_path") or "").strip()
            if not external_path:
                continue
            try:
                checkpoint_id = int(item.get("id"))
                completed_at = int(
                    item.get("latest_ack_timestamp")
                    or item.get("trigger_timestamp")
                    or 0
                )
            except (TypeError, ValueError):
                continue
            checkpoints.append(
                CompletedCheckpoint(
                    checkpoint_id=checkpoint_id,
                    external_path=external_path,
                    completed_at_millis=completed_at,
                )
            )
        return max(
            checkpoints,
            key=lambda item: (item.completed_at_millis, item.checkpoint_id),
            default=None,
        )


def submission_decision(jobs: Iterable[Job], required_name: str) -> SubmissionDecision:
    matches = tuple(job for job in jobs if job.name == required_name)
    running = next((job for job in matches if job.state == RUNNING_STATE), None)
    if running:
        return SubmissionDecision("satisfied", running, matches)
    active = next((job for job in matches if job.state not in TERMINAL_STATES), None)
    if active:
        return SubmissionDecision("wait", active, matches)
    return SubmissionDecision("submit", None, matches)


def _format_jobs(jobs: Sequence[Job]) -> str:
    if not jobs:
        return "none"
    return ", ".join(
        f"{job.name}={job.state} ({job.job_id})"
        for job in sorted(jobs, key=lambda item: (item.name, item.job_id))
    )


def wait_for_flink(
    client: FlinkRestClient,
    config: BootstrapConfig,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Job]:
    for attempt in range(1, config.max_attempts + 1):
        LOGGER.info(
            "Checking Flink REST endpoint %s (attempt %d/%d)",
            config.rest_url,
            attempt,
            config.max_attempts,
        )
        try:
            jobs = client.list_jobs()
        except FlinkUnavailable as exc:
            if attempt == config.max_attempts:
                raise FlinkUnavailable(
                    f"Flink remained unavailable after {config.max_attempts} attempts: {exc}"
                ) from exc
            LOGGER.warning(
                "Flink availability check failed with %s; retrying in %g seconds",
                type(exc).__name__,
                config.poll_interval_seconds,
            )
            sleep(config.poll_interval_seconds)
            continue
        LOGGER.info("Existing Flink jobs: %s", _format_jobs(jobs))
        return jobs
    raise AssertionError("unreachable")


def submit_python_job(
    config: BootstrapConfig,
    required_name: str,
    restore_path: str | None = None,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    source_file = config.files_root / JOB_FILES[required_name]
    command = [
        config.flink_binary,
        "run",
        "-d",
        "-m",
        config.cli_jobmanager,
        "-py",
        str(source_file),
        "-pyfs",
        str(config.files_root.parent),
        "-pyclientexec",
        config.python_client_executable,
        "--jarfile",
        str(config.kafka_connector_jar),
    ]
    if restore_path:
        command.extend(["-s", restore_path])
    try:
        result = run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=config.submission_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise BootstrapError(
            f"Flink CLI submission timed out for '{required_name}'"
        ) from exc
    except OSError as exc:
        raise BootstrapError(
            f"Flink CLI could not start for '{required_name}' ({type(exc).__name__})"
        ) from exc
    if result.returncode != 0:
        raise BootstrapError(
            f"Flink CLI exited with status {result.returncode} for '{required_name}'"
        )
    match = JOB_ID_PATTERN.search((result.stdout or "") + "\n" + (result.stderr or ""))
    if match is None:
        raise BootstrapError(
            f"Flink CLI did not return a job ID for '{required_name}'"
        )
    return match.group(1).lower()


def wait_for_job(
    client: FlinkRestClient,
    expected: Job,
    config: BootstrapConfig,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Job:
    deadline = monotonic() + config.start_timeout_seconds
    last_state = "NOT_VISIBLE"
    while True:
        try:
            observed = client.get_job(expected.job_id)
        except FlinkUnavailable as exc:
            observed = None
            if last_state != "REST_UNAVAILABLE":
                LOGGER.warning(
                    "Flink REST was temporarily unavailable while waiting for '%s' "
                    "(%s)",
                    expected.name,
                    type(exc).__name__,
                )
                last_state = "REST_UNAVAILABLE"
        if observed is not None:
            if observed.name != expected.name:
                raise BootstrapError(
                    f"Flink job ID {expected.job_id} resolved to unexpected name "
                    f"'{observed.name}' instead of '{expected.name}'"
                )
            if observed.state != last_state:
                LOGGER.info(
                    "Flink job '%s' (%s) state: %s",
                    observed.name,
                    observed.job_id,
                    observed.state,
                )
                last_state = observed.state
            if observed.state == RUNNING_STATE:
                return observed
            if observed.state in TERMINAL_STATES:
                raise JobTerminalError(
                    f"Flink job '{observed.name}' ({observed.job_id}) reached "
                    f"terminal state {observed.state}"
                )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise BootstrapError(
                f"Timed out waiting for Flink job '{expected.name}' "
                f"({expected.job_id}) to reach RUNNING; final state was {last_state}"
            )
        sleep(min(config.poll_interval_seconds, remaining))


def ensure_job(
    client: FlinkRestClient,
    config: BootstrapConfig,
    required_name: str,
    *,
    submit: Callable[[BootstrapConfig, str, str | None], str] = submit_python_job,
    sleep: Callable[[float], None] = time.sleep,
) -> Job:
    for attempt in range(1, config.max_attempts + 1):
        # This REST re-query occurs immediately before every possible submission.
        try:
            jobs = client.list_jobs()
        except FlinkUnavailable as exc:
            if attempt == config.max_attempts:
                raise
            LOGGER.warning(
                "Could not re-query Flink before handling '%s' (%s); retrying in "
                "%g seconds",
                required_name,
                type(exc).__name__,
                config.poll_interval_seconds,
            )
            sleep(config.poll_interval_seconds)
            continue
        decision = submission_decision(jobs, required_name)
        if decision.action == "satisfied":
            LOGGER.info(
                "Required Flink job '%s' is already RUNNING as %s",
                required_name,
                decision.job.job_id,
            )
            return decision.job
        if decision.action == "wait":
            LOGGER.info(
                "Required Flink job '%s' already exists in non-terminal state %s; "
                "waiting instead of submitting a duplicate",
                required_name,
                decision.job.state,
            )
            try:
                return wait_for_job(client, decision.job, config, sleep=sleep)
            except JobTerminalError:
                if attempt == config.max_attempts:
                    raise
                LOGGER.warning(
                    "Existing Flink job '%s' entered a terminal state; re-querying "
                    "before a deliberate resubmission decision",
                    required_name,
                )
                continue

        terminal_matches = [
            job for job in decision.matches if job.state in TERMINAL_STATES
        ]
        restore_checkpoint = None
        if terminal_matches:
            LOGGER.info(
                "Required Flink job '%s' has only terminal instances (%s); "
                "deliberately resubmitting",
                required_name,
                _format_jobs(terminal_matches),
            )
            retained = []
            for terminal_job in terminal_matches:
                checkpoint = client.latest_completed_checkpoint(terminal_job.job_id)
                if checkpoint is not None:
                    retained.append((checkpoint, terminal_job))
            if retained:
                restore_checkpoint, checkpoint_job = max(
                    retained,
                    key=lambda item: (
                        item[0].completed_at_millis,
                        item[0].checkpoint_id,
                    ),
                )
                LOGGER.info(
                    "Restoring '%s' from retained checkpoint %s of terminal job %s",
                    required_name,
                    restore_checkpoint.checkpoint_id,
                    checkpoint_job.job_id,
                )
            else:
                LOGGER.info(
                    "No retained completed checkpoint is exposed for terminal job "
                    "'%s'; resubmitting with its preserved Kafka offset policy",
                    required_name,
                )
        else:
            LOGGER.info("Required Flink job '%s' is missing", required_name)
        LOGGER.info(
            "Submitting Flink job '%s' with the Flink CLI (attempt %d/%d)",
            required_name,
            attempt,
            config.max_attempts,
        )
        try:
            job_id = submit(
                config,
                required_name,
                restore_checkpoint.external_path if restore_checkpoint else None,
            )
        except BootstrapError as exc:
            if attempt == config.max_attempts:
                raise
            LOGGER.warning(
                "Submission attempt for '%s' failed with %s; re-querying Flink "
                "before retrying in %g seconds",
                required_name,
                type(exc).__name__,
                config.poll_interval_seconds,
            )
            sleep(config.poll_interval_seconds)
            continue
        LOGGER.info("Submitted Flink job '%s' with job ID %s", required_name, job_id)
        submitted = Job(job_id=job_id, name=required_name, state="SUBMITTED")
        try:
            return wait_for_job(client, submitted, config, sleep=sleep)
        except JobTerminalError:
            if attempt == config.max_attempts:
                raise
            LOGGER.warning(
                "Submitted Flink job '%s' entered a terminal state; re-querying "
                "before retrying in %g seconds",
                required_name,
                config.poll_interval_seconds,
            )
            sleep(config.poll_interval_seconds)
    raise AssertionError("unreachable")


@contextmanager
def postgresql_bootstrap_lock(
    config: BootstrapConfig,
    *,
    connect: Callable[..., object] = psycopg.connect,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[None]:
    try:
        connection = connect(
            config.database_url,
            autocommit=True,
            connect_timeout=max(1, min(10, int(config.rest_timeout_seconds))),
        )
    except Exception as exc:
        raise BootstrapError(
            "Could not connect to PostgreSQL for the Flink bootstrap lock "
            f"({type(exc).__name__})"
        ) from exc

    acquired = False
    try:
        for attempt in range(1, config.max_attempts + 1):
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_lock(%s)",
                    (ADVISORY_LOCK_KEY,),
                )
                acquired = bool(cursor.fetchone()[0])
            if acquired:
                LOGGER.info("Acquired distributed Flink bootstrap lock")
                break
            if attempt < config.max_attempts:
                LOGGER.info(
                    "Another Backend replica holds the Flink bootstrap lock; "
                    "retrying in %g seconds (%d/%d)",
                    config.poll_interval_seconds,
                    attempt,
                    config.max_attempts,
                )
                sleep(config.poll_interval_seconds)
        if not acquired:
            raise BootstrapError(
                "Timed out waiting for the distributed Flink bootstrap lock"
            )
        yield
    finally:
        if acquired:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_unlock(%s)",
                        (ADVISORY_LOCK_KEY,),
                    )
            except Exception:
                LOGGER.warning("Could not explicitly release the Flink bootstrap lock")
        connection.close()


def ensure_required_flink_jobs(
    config: BootstrapConfig | None = None,
    *,
    client: FlinkRestClient | None = None,
    submit: Callable[[BootstrapConfig, str, str | None], str] = submit_python_job,
    lock: Callable[[BootstrapConfig], object] = postgresql_bootstrap_lock,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Job]:
    config = config or BootstrapConfig.from_environment()
    if not config.enabled:
        LOGGER.info("Flink automatic job submission is disabled")
        return []

    config.validate()
    LOGGER.info("Required Flink jobs: %s", ", ".join(config.required_jobs))
    client = client or FlinkRestClient(config.rest_url, config.rest_timeout_seconds)

    with lock(config):
        initial_jobs = wait_for_flink(client, config, sleep=sleep)
        missing_jobs = [
            name
            for name in config.required_jobs
            if not any(job.name == name for job in initial_jobs)
        ]
        LOGGER.info(
            "Missing required Flink jobs: %s",
            ", ".join(missing_jobs) if missing_jobs else "none",
        )
        for name in config.required_jobs:
            ensure_job(client, config, name, submit=submit, sleep=sleep)

        final_jobs = client.list_jobs()
        LOGGER.info("Final Flink jobs: %s", _format_jobs(final_jobs))
        unresolved = []
        running = []
        for name in config.required_jobs:
            decision = submission_decision(final_jobs, name)
            if decision.action == "satisfied":
                running.append(decision.job)
            else:
                states = ",".join(job.state for job in decision.matches) or "MISSING"
                unresolved.append(f"{name}={states}")
        if unresolved:
            raise BootstrapError(
                "Required Flink jobs are not RUNNING after bootstrap: "
                + ", ".join(unresolved)
            )
        return running


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    try:
        ensure_required_flink_jobs()
    except BootstrapError as exc:
        LOGGER.error("Flink job bootstrap failed [%s]: %s", type(exc).__name__, exc)
        return 1
    LOGGER.info("Flink job bootstrap completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
