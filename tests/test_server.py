# SPDX-License-Identifier: AGPL-3.0-only
"""Integration tests for the local API and job manager."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atap.server import JobManager, ServerConfig, create_app
from atap.server.app import Job, _validate_params

FOOTPRINT = json.dumps({
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"id": "one"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [119.4, -5.1], [119.4001, -5.1],
                [119.4001, -5.1001], [119.4, -5.1001],
                [119.4, -5.1],
            ]],
        },
    }],
}).encode()


def _wait(manager: JobManager, job_id: str, states: set[str], timeout: float = 10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.jobs[job_id].status
        if status in states:
            return status
        time.sleep(0.05)
    raise AssertionError(f"job remained {manager.jobs[job_id].status}")


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _result_command(_job):
    code = (
        "import json;"
        "print(json.dumps({'type':'progress','current':1,'total':1,"
        "'message':'done'}),flush=True);"
        "print(json.dumps({'type':'result','num_features':1,"
        "'num_buildings':1,'num_skipped':0}),flush=True)"
    )
    return [sys.executable, "-c", code]


def _files(raster: bytes = b"dummy"):
    return {
        "footprint": ("input.geojson", FOOTPRINT, "application/geo+json"),
        "dsm": ("surface.tif", raster, "image/tiff"),
        "dtm": ("terrain.tif", raster, "image/tiff"),
    }


def test_health_static_submit_status_events_and_artifact(tmp_path: Path):
    config = ServerConfig(work_dir=tmp_path)
    manager = JobManager(config, _result_command)
    with TestClient(create_app(config, manager)) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["source_url"].startswith("https://github.com/")
        assert client.get("/").status_code == 200

        created = client.post(
            "/api/jobs", files=_files(),
            data={"params": json.dumps({"regularize": False})},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["footprint_count"] == 1
        assert _wait(manager, body["job_id"], {"completed"}) == "completed"
        status = client.get(f"/api/jobs/{body['job_id']}").json()
        assert status["result"]["num_features"] == 1
        events = client.get(f"/api/jobs/{body['job_id']}/events")
        assert '"type": "started"' in events.text
        assert '"type": "completed"' in events.text
        assert '"type": "close"' in events.text
        assert client.get(
            f"/api/jobs/{body['job_id']}/artifacts/log"
        ).status_code == 200
        assert client.get(
            f"/api/jobs/{body['job_id']}/artifacts/params"
        ).status_code == 404


def test_rejects_unknown_parameter_and_oversized_upload(tmp_path: Path):
    config = ServerConfig(work_dir=tmp_path, max_upload_mb=1)
    manager = JobManager(config, _result_command)
    with TestClient(create_app(config, manager)) as client:
        response = client.post(
            "/api/jobs", files=_files(),
            data={"params": '{"surprise": true}'},
        )
        assert response.status_code == 422
        response = client.post(
            "/api/jobs",
            files=_files(b"x" * (1024 * 1024)),
            data={"params": "{}"},
        )
        assert response.status_code == 413
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ('{"regularize": 1}', "boolean"),
        ('{"max_height_classes": 0}', "1 to 32"),
        ('{"rectangular_ratio": 2}', "between 0 and 1"),
        ('{"keep_properties": "name"}', "array of strings"),
        ('{"height_diff_threshold_m": 1e999}', "non-negative"),
    ],
)
def test_parameter_type_and_range_validation(params: str, message: str):
    with pytest.raises(Exception) as caught:
        _validate_params(params)
    assert message in str(caught.value.detail)


def test_fifo_queued_and_running_cancellation(tmp_path: Path):
    config = ServerConfig(
        work_dir=tmp_path, max_concurrent=1, grace_seconds=0.1
    )
    def tree_command(job):
        sleeping = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"pathlib.Path({str(job.directory / 'child.pid')!r}).write_text(str(child.pid));"
        "print('{\"type\":\"progress\",\"current\":0,"
        "\"total\":1,\"message\":\"waiting\"}',flush=True);"
        "time.sleep(60)"
        )
        return [sys.executable, "-c", sleeping]

    manager = JobManager(config, tree_command)
    first_dir = tmp_path / str(__import__("uuid").uuid4())
    second_dir = tmp_path / str(__import__("uuid").uuid4())
    first_dir.mkdir()
    second_dir.mkdir()
    first = manager.submit(first_dir, 1)
    second = manager.submit(second_dir, 1)
    assert _wait(manager, first.job_id, {"running"}) == "running"
    pid_file = first_dir / "child.pid"
    deadline = time.time() + 5
    while not pid_file.exists() and time.time() < deadline:
        time.sleep(0.05)
    child_pid = int(pid_file.read_text())
    assert manager.snapshot(second)["queue_position"] == 1
    manager.cancel(second)
    assert second.status == "cancelled"
    manager.cancel(first)
    assert _wait(manager, first.job_id, {"cancelled"}, timeout=5) == "cancelled"
    assert not manager.running
    deadline = time.time() + 5
    while _pid_alive(child_pid) and time.time() < deadline:
        time.sleep(0.05)
    assert not _pid_alive(child_pid)
    manager.close()


def test_startup_ttl_cleanup_only_removes_uuid_directories(tmp_path: Path):
    expired = tmp_path / "00000000-0000-0000-0000-000000000001"
    preserved = tmp_path / "keep-me"
    expired.mkdir()
    preserved.mkdir()
    old = time.time() - 7200
    os.utime(expired, (old, old))
    os.utime(preserved, (old, old))
    manager = JobManager(
        ServerConfig(work_dir=tmp_path, job_ttl_hours=1), _result_command
    )
    assert not expired.exists()
    assert preserved.exists()
    manager.close()


def test_server_import_does_not_load_pipeline():
    code = (
        "import sys; from atap.server import create_app; "
        "assert 'atap.engine.pipeline' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_real_cli_job_and_disguised_vrt(tmp_path: Path, synthetic: Path):
    config = ServerConfig(work_dir=tmp_path, grace_seconds=1)
    manager = JobManager(config)
    source = synthetic / "stepped"
    with TestClient(create_app(config, manager)) as client:
        with (
            (source / "footprints.geojson").open("rb") as footprint,
            (source / "dsm.tif").open("rb") as dsm,
            (source / "dtm.tif").open("rb") as dtm,
        ):
            response = client.post(
                "/api/jobs",
                files={"footprint": footprint, "dsm": dsm, "dtm": dtm},
                data={"params": '{"id_field": "id"}'},
            )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        assert _wait(manager, job_id, {"completed", "failed"}, 30) == "completed"
        assert client.get(
            f"/api/jobs/{job_id}/artifacts/output"
        ).status_code == 200

        first_output = client.get(f"/api/jobs/{job_id}/artifacts/output").json()
        reused = client.post("/api/jobs", data={
            "source_job_id": job_id, "params": '{"id_field":"id","workers":2}',
        })
        assert reused.status_code == 200
        reused_id = reused.json()["job_id"]
        assert _wait(manager, reused_id, {"completed", "failed"}, 30) == "completed"
        second_output = client.get(f"/api/jobs/{reused_id}/artifacts/output").json()
        for output in (first_output, second_output):
            output.pop("process")
            output["processing"].pop("execution")
        assert first_output == second_output

        disguised = b'<VRTDataset rasterXSize="1" rasterYSize="1"/>'
        response = client.post(
            "/api/jobs", files=_files(disguised),
            data={"params": '{"id_field": "id"}'},
        )
        assert response.status_code == 200
        invalid_id = response.json()["job_id"]
        assert _wait(manager, invalid_id, {"failed"}, 15) == "failed"
        assert manager.jobs[invalid_id].error["code"] == "INPUT"


def test_reuse_keeps_one_input_copy_and_separate_outputs(tmp_path):
    config = ServerConfig(work_dir=tmp_path)
    manager = JobManager(config, _result_command)
    with TestClient(create_app(config, manager)) as client:
        first_id = client.post("/api/jobs", files=_files()).json()["job_id"]
        _wait(manager, first_id, {"completed"})
        source = manager.jobs[first_id]
        reused = client.post("/api/jobs", data={
            "source_job_id": first_id, "params": '{"workers": 2}',
        })
        assert reused.status_code == 200
        second_id = reused.json()["job_id"]
        _wait(manager, second_id, {"completed"})
        second = manager.jobs[second_id]
        assert second.input_directory == source.directory
        assert not (second.directory / "dsm.tif").exists()
        assert json.loads((second.directory / "params.json").read_text())["workers"] == 2
        command = manager._default_command(second)
        assert command[command.index("--dsm") + 1] == str(source.directory / "dsm.tif")
        assert command[command.index("--cancel-file") + 1] == str(second.directory / "CANCEL")
        (source.directory / "output.geojson").write_text("first")
        (second.directory / "output.geojson").write_text("second")
        names = []
        for job_id, content in [(first_id, "first"), (second_id, "second")]:
            response = client.get(f"/api/jobs/{job_id}/artifacts/output")
            assert response.text == content
            header = response.headers["content-disposition"]
            assert re.search(r'atap_\d{8}T\d{6}Z_' + job_id[:8] + r'\.geojson', header)
            names.append(header)
        assert names[0] != names[1]
        third = client.post("/api/jobs", data={"source_job_id": second_id})
        assert third.status_code == 200
        assert manager.jobs[third.json()["job_id"]].input_directory == source.directory
        _wait(manager, third.json()["job_id"], {"completed"})


def test_reuse_rejects_missing_unknown_and_mixed_sources(tmp_path):
    config = ServerConfig(work_dir=tmp_path)
    manager = JobManager(config, _result_command)
    with TestClient(create_app(config, manager)) as client:
        assert client.post("/api/jobs", data={"params": "{}"}).status_code == 422
        assert client.post("/api/jobs", data={"source_job_id": "../../outside"}).status_code == 404
        assert client.post("/api/jobs", files=_files(),
                           data={"source_job_id": "unknown"}).status_code == 422
        first_id = client.post("/api/jobs", files=_files()).json()["job_id"]
        _wait(manager, first_id, {"completed"})
        old = time.time() - 48 * 3600
        os.utime(manager.jobs[first_id].directory, (old, old))
        manager.cleanup_expired()
        assert client.post("/api/jobs", data={"source_job_id": first_id}).status_code == 404


def test_ttl_preserves_shared_inputs_for_queued_and_running_jobs(tmp_path):
    config = ServerConfig(work_dir=tmp_path, job_ttl_hours=1)
    manager = JobManager(config, _result_command)
    try:
        source_dir = tmp_path / "00000000-0000-0000-0000-000000000001"
        source_dir.mkdir()
        consumer_dir = tmp_path / "00000000-0000-0000-0000-000000000002"
        consumer_dir.mkdir()
        source = Job(source_dir.name, source_dir, 1, status="completed")
        consumer = Job(consumer_dir.name, consumer_dir, 1, input_directory=source_dir)
        manager.jobs.update({source.job_id: source, consumer.job_id: consumer})
        old = time.time() - 7200
        for status in ("queued", "running"):
            consumer.status = status
            for directory in (source_dir, consumer_dir):
                os.utime(directory, (old, old))
            manager.cleanup_expired()
            assert source_dir.exists() and consumer_dir.exists()
        consumer.status = "completed"
        manager.cleanup_expired()
        assert not source_dir.exists() and not consumer_dir.exists()
    finally:
        manager.close()
