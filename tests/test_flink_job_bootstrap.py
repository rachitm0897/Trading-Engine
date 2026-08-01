from __future__ import annotations

import subprocess
import zipfile
from contextlib import contextmanager
from dataclasses import replace

import pytest

from scripts.ensure_flink_jobs import (
    BootstrapConfig,
    BootstrapError,
    CompletedCheckpoint,
    ConfigurationError,
    FlinkRestClient,
    Job,
    ensure_job,
    ensure_required_flink_jobs,
    submission_decision,
    submit_python_job,
    wait_for_completed_checkpoint,
)
from streaming.flink.jobs.python_worker import WorkerPythonConfig


def config_for(tmp_path, *, required_jobs=("market-normalization-v2",), attempts=3):
    files_root = tmp_path / "flink" / "jobs"
    files_root.mkdir(parents=True)
    (files_root / "market_normalization.py").write_text("pass\n", encoding="utf-8")
    flink_binary = tmp_path / "flink-cli"
    flink_binary.write_text("", encoding="utf-8")
    python_client = tmp_path / "python3.11"
    python_client.write_text("", encoding="utf-8")
    connector_jar = tmp_path / "flink-sql-connector-kafka.jar"
    connector_jar.write_text("", encoding="utf-8")
    worker_archive = tmp_path / "flink-python-runtime.zip"
    with zipfile.ZipFile(worker_archive, "w") as archive:
        info = zipfile.ZipInfo("bin/python")
        info.external_attr = 0o100755 << 16
        archive.writestr(info, b"portable-python")
    return BootstrapConfig(
        enabled=True,
        rest_url="http://flink-jobmanager:8081",
        cli_jobmanager="flink-jobmanager:8081",
        required_jobs=required_jobs,
        files_root=files_root,
        flink_binary=str(flink_binary),
        python_client_executable=str(python_client),
        kafka_connector_jar=connector_jar,
        database_url="postgresql://example.invalid/backend",
        submission_timeout_seconds=10,
        start_timeout_seconds=10,
        poll_interval_seconds=0.001,
        max_attempts=attempts,
        rest_timeout_seconds=2,
        worker_python=WorkerPythonConfig(
            runtime_mode="archive",
            executable="pyenv/bin/python",
            archive_path=worker_archive,
            archive_target="pyenv",
        ),
        cancel_timeout_seconds=1,
        checkpoint_timeout_seconds=0,
        repair_status_path=tmp_path / "flink-bootstrap-status.json",
    )


class FakeClient:
    def __init__(
        self,
        overviews,
        details=None,
        checkpoints=None,
        root_exceptions=None,
    ):
        self.overviews = list(overviews)
        self.details = {
            job_id: list(observations)
            for job_id, observations in (details or {}).items()
        }
        self.list_calls = 0
        self.checkpoints = checkpoints or {}
        self.root_exceptions = root_exceptions or {}
        self.cancellations = []

    def list_jobs(self):
        self.list_calls += 1
        if len(self.overviews) > 1:
            return self.overviews.pop(0)
        return self.overviews[0]

    def get_job(self, job_id):
        observations = self.details[job_id]
        if len(observations) > 1:
            return observations.pop(0)
        return observations[0]

    def latest_completed_checkpoint(self, job_id):
        return self.checkpoints.get(job_id)

    def root_exception(self, job_id):
        return self.root_exceptions.get(job_id)

    def cancel_job(self, job_id):
        self.cancellations.append(job_id)


def test_rest_discovery_reads_overview_and_job_details():
    job_id = "9" * 32

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout):
            self.calls.append((url, timeout))
            if url.endswith("/jobs/overview"):
                return Response(
                    {
                        "jobs": [
                            {
                                "jid": job_id,
                                "name": "market-normalization-v2",
                                "state": "RUNNING",
                            }
                        ]
                    }
                )
            if url.endswith("/checkpoints"):
                return Response(
                    {
                        "latest": {
                            "completed": {
                                "id": 8,
                                "status": "COMPLETED",
                                "latest_ack_timestamp": 200,
                                "external_path": "file:///checkpoints/8",
                            }
                        },
                        "history": [
                            {
                                "id": 7,
                                "status": "COMPLETED",
                                "latest_ack_timestamp": 100,
                                "external_path": "file:///checkpoints/7",
                            }
                        ],
                    }
                )
            return Response(
                {
                    "jid": job_id,
                    "name": "market-normalization-v2",
                    "state": "RUNNING",
                }
            )

    session = Session()
    client = FlinkRestClient(
        "http://flink-jobmanager:8081",
        3,
        session=session,
    )

    expected = Job(job_id, "market-normalization-v2", "RUNNING")
    assert client.list_jobs() == [expected]
    assert client.get_job(job_id) == expected
    assert client.latest_completed_checkpoint(job_id) == CompletedCheckpoint(
        8,
        "file:///checkpoints/8",
        200,
    )
    assert session.calls == [
        ("http://flink-jobmanager:8081/jobs/overview", 3),
        (f"http://flink-jobmanager:8081/jobs/{job_id}", 3),
        (f"http://flink-jobmanager:8081/jobs/{job_id}/checkpoints", 3),
    ]


def test_submission_decision_prefers_running_and_blocks_on_transitional_jobs():
    name = "market-normalization-v2"
    failed = Job("failed", name, "FAILED")
    initializing = Job("starting", name, "INITIALIZING")
    running = Job("running", name, "RUNNING")

    assert submission_decision([failed], name).action == "submit"
    assert submission_decision([failed, initializing], name).action == "wait"
    assert submission_decision([Job("unknown", name, "UNKNOWN")], name).action == "wait"
    decision = submission_decision([failed, initializing, running], name)
    assert decision.action == "satisfied"
    assert decision.job == running


def test_rest_cancellation_uses_flink_cancel_mode():
    class Response:
        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.calls = []

        def patch(self, url, params, timeout):
            self.calls.append((url, params, timeout))
            return Response()

    session = Session()
    client = FlinkRestClient(
        "http://flink-jobmanager:8081",
        3,
        session=session,
    )

    client.cancel_job("a" * 32)

    assert session.calls == [
        (
            "http://flink-jobmanager:8081/jobs/" + "a" * 32,
            {"mode": "cancel"},
            3,
        )
    ]


def test_unknown_required_job_fails_configuration_validation(tmp_path):
    config = config_for(tmp_path, required_jobs=("unknown-flink-job",))

    with pytest.raises(ConfigurationError, match="No Flink source mapping"):
        config.validate()


def test_missing_mapped_source_fails_configuration_validation(tmp_path):
    config = config_for(tmp_path)
    (config.files_root / "market_normalization.py").unlink()

    with pytest.raises(ConfigurationError, match="source file.*missing"):
        config.validate()


def test_running_job_is_preserved_without_submission(tmp_path):
    config = config_for(tmp_path)
    running = Job("a" * 32, config.required_jobs[0], "RUNNING")
    client = FakeClient([[running]])
    submissions = []

    result = ensure_job(
        client,
        config,
        config.required_jobs[0],
        submit=lambda *args: submissions.append(args),
        sleep=lambda _: None,
    )

    assert result == running
    assert submissions == []


def test_transitional_job_is_waited_for_without_duplicate_submission(tmp_path):
    config = config_for(tmp_path)
    name = config.required_jobs[0]
    job_id = "b" * 32
    initializing = Job(job_id, name, "INITIALIZING")
    running = Job(job_id, name, "RUNNING")
    client = FakeClient([[initializing]], {job_id: [initializing, running]})
    submissions = []

    result = ensure_job(
        client,
        config,
        name,
        submit=lambda *args: submissions.append(args),
        sleep=lambda _: None,
    )

    assert result == running
    assert submissions == []


def test_terminal_job_is_deliberately_resubmitted_and_verified(tmp_path):
    config = config_for(tmp_path)
    name = config.required_jobs[0]
    old = Job("c" * 32, name, "FAILED")
    new = Job("d" * 32, name, "RUNNING")
    client = FakeClient([[old]], {new.job_id: [new]})
    submissions = []

    checkpoint = CompletedCheckpoint(7, "file:///checkpoints/7", 123456)

    def submit(_config, required_name, restore_path):
        submissions.append((required_name, restore_path))
        return new.job_id

    client.checkpoints[old.job_id] = checkpoint

    result = ensure_job(
        client,
        config,
        name,
        submit=submit,
        sleep=lambda _: None,
    )

    assert result == new
    assert submissions == [(name, checkpoint.external_path)]
    assert client.list_calls == 1


def test_failed_cli_attempt_requeries_and_observes_concurrent_job(tmp_path):
    config = config_for(tmp_path)
    name = config.required_jobs[0]
    concurrent = Job("e" * 32, name, "INITIALIZING")
    running = Job(concurrent.job_id, name, "RUNNING")
    client = FakeClient([[], [concurrent]], {concurrent.job_id: [running]})
    submissions = []

    def submit(_config, required_name, _restore_path):
        submissions.append(required_name)
        raise BootstrapError("simulated ambiguous submission failure")

    result = ensure_job(
        client,
        config,
        name,
        submit=submit,
        sleep=lambda _: None,
    )

    assert result == running
    assert submissions == [name]
    assert client.list_calls == 2


def test_cli_submission_ships_dependencies_and_checkpoint_restore_path(tmp_path):
    config = config_for(tmp_path)
    captured = {}
    submitted_id = "f" * 32

    def run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"Job has been submitted with JobID {submitted_id}\n",
            stderr="",
        )

    restore_path = "file:///checkpoints/7"
    result = submit_python_job(
        config,
        config.required_jobs[0],
        restore_path,
        run=run,
    )

    assert result == submitted_id
    assert captured["command"] == [
        config.flink_binary,
        "run",
        "-d",
        "-m",
        "flink-jobmanager:8081",
        "-py",
        str(config.files_root / "market_normalization.py"),
        "-pyfs",
        str(config.files_root.parent),
        "-pyclientexec",
        config.python_client_executable,
        "--jarfile",
        str(config.kafka_connector_jar),
        "-s",
        restore_path,
    ]
    assert captured["kwargs"]["timeout"] == 10
    assert captured["kwargs"]["capture_output"] is True


def test_full_bootstrap_is_idempotent_across_repeated_runs(tmp_path):
    config = config_for(tmp_path)
    name = config.required_jobs[0]

    class StatefulClient:
        job = None

        def list_jobs(self):
            return [self.job] if self.job else []

        def get_job(self, job_id):
            assert self.job.job_id == job_id
            return self.job

    client = StatefulClient()
    submissions = []

    def submit(_config, required_name, _restore_path):
        submissions.append(required_name)
        client.job = Job("1" * 32, required_name, "RUNNING")
        return client.job.job_id

    @contextmanager
    def lock(_config):
        yield

    first = ensure_required_flink_jobs(
        config,
        client=client,
        submit=submit,
        lock=lock,
        sleep=lambda _: None,
    )
    second = ensure_required_flink_jobs(
        config,
        client=client,
        submit=submit,
        lock=lock,
        sleep=lambda _: None,
    )

    assert first == second == [client.job]
    assert submissions == [name]


def test_restarting_job_with_known_missing_python_is_canceled_and_replaced(tmp_path):
    config = config_for(tmp_path)
    name = config.required_jobs[0]
    old = Job("2" * 32, name, "RESTARTING")
    canceled = Job(old.job_id, name, "CANCELED")
    replacement = Job("3" * 32, name, "RUNNING")

    class RepairClient:
        current = old

        def __init__(self):
            self.cancellations = []

        def list_jobs(self):
            return [self.current]

        def get_job(self, job_id):
            if job_id == old.job_id and self.current.state == "CANCELLING":
                self.current = canceled
            return self.current

        def root_exception(self, job_id):
            assert job_id == old.job_id
            return 'java.io.IOException: Cannot run program "python": error=2, No such file or directory'

        def latest_completed_checkpoint(self, _job_id):
            return None

        def cancel_job(self, job_id):
            self.cancellations.append(job_id)
            self.current = Job(job_id, name, "CANCELLING")

    client = RepairClient()
    submissions = []
    reports = []

    def submit(_config, required_name, restore_path):
        submissions.append((required_name, restore_path))
        client.current = replacement
        return replacement.job_id

    result = ensure_job(
        client,
        config,
        name,
        submit=submit,
        reporter=lambda *args, **kwargs: reports.append((args, kwargs)),
        sleep=lambda _: None,
    )

    assert result == replacement
    assert client.cancellations == [old.job_id]
    assert submissions == [(name, None)]
    assert [item[0][1] for item in reports] == [
        "CANCEL_REQUESTED",
        "CANCELED",
        "REPAIRED",
    ]


def test_restarting_job_with_unknown_cause_is_not_canceled(tmp_path):
    config = config_for(tmp_path)
    name = config.required_jobs[0]
    old = Job("4" * 32, name, "RESTARTING")
    client = FakeClient(
        [[old]],
        root_exceptions={old.job_id: "Kafka broker connection timed out"},
    )

    with pytest.raises(BootstrapError, match="will not be canceled automatically"):
        ensure_job(client, config, name, sleep=lambda _: None)

    assert client.cancellations == []


def test_known_python_repair_can_be_disabled(tmp_path):
    config = config_for(tmp_path)
    config = replace(
        config,
        auto_repair_python_executable_failure=False,
    )
    name = config.required_jobs[0]
    old = Job("5" * 32, name, "RESTARTING")
    client = FakeClient(
        [[old]],
        root_exceptions={
            old.job_id: 'Cannot run program "python": No such file or directory'
        },
    )

    with pytest.raises(BootstrapError, match="automatic repair is disabled"):
        ensure_job(client, config, name, sleep=lambda _: None)

    assert client.cancellations == []


def test_new_running_job_waits_for_first_completed_checkpoint(tmp_path):
    config = replace(config_for(tmp_path), checkpoint_timeout_seconds=1)
    job = Job("6" * 32, config.required_jobs[0], "RUNNING")
    checkpoint = CompletedCheckpoint(9, "", 123456)

    class CheckpointClient:
        observations = iter([None, checkpoint])

        def get_job(self, job_id):
            assert job_id == job.job_id
            return job

        def latest_completed_checkpoint(self, job_id):
            assert job_id == job.job_id
            return next(self.observations)

    sleeps = []
    result = wait_for_completed_checkpoint(
        CheckpointClient(),
        job,
        config,
        sleep=sleeps.append,
    )

    assert result == checkpoint
    assert sleeps == [config.poll_interval_seconds]


def test_postgresql_lock_waits_then_releases(tmp_path):
    from scripts.ensure_flink_jobs import postgresql_bootstrap_lock

    config = config_for(tmp_path)
    lock_results = iter([False, True])

    class Cursor:
        def __init__(self, connection):
            self.connection = connection
            self.result = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, statement, parameters):
            self.connection.statements.append((statement, parameters))
            if "pg_try_advisory_lock" in statement:
                self.result = next(lock_results)

        def fetchone(self):
            return (self.result,)

    class Connection:
        def __init__(self):
            self.statements = []
            self.closed = False

        def cursor(self):
            return Cursor(self)

        def close(self):
            self.closed = True

    connection = Connection()
    connect_arguments = {}
    sleeps = []

    def connect(*args, **kwargs):
        connect_arguments["args"] = args
        connect_arguments["kwargs"] = kwargs
        return connection

    with postgresql_bootstrap_lock(
        config,
        connect=connect,
        sleep=sleeps.append,
    ):
        assert connection.closed is False

    assert connect_arguments["args"] == (config.database_url,)
    assert connect_arguments["kwargs"]["autocommit"] is True
    assert sleeps == [config.poll_interval_seconds]
    assert sum("pg_try_advisory_lock" in row[0] for row in connection.statements) == 2
    assert sum("pg_advisory_unlock" in row[0] for row in connection.statements) == 1
    assert connection.closed is True
