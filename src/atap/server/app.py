# SPDX-License-Identifier: AGPL-3.0-only
"""Local FastAPI service and isolated CLI job runner."""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import warnings
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from atap import __version__

SOURCE_URL = "https://github.com/enygma-id/atap"
UPLOAD_CHUNK = 1024 * 1024
MAX_FOOTPRINTS = 1_000_000
TERMINAL_STATES = {"completed", "failed", "cancelled"}
PARAMETERS = {
    "id_field", "height_diff_threshold_m", "min_subregion_area_m2",
    "min_building_height_m", "base_elevation_stat", "ground_source_type",
    "vertical_datum", "max_height_classes", "min_footprint_change_ratio",
    "morph_closing_iters", "max_fill_hole_area_m2",
    "parent_min_containment_ratio", "regularize", "simplify_tolerance_m",
    "rectangular_ratio", "circularity_threshold", "keep_properties",
    "working_crs", "round_digits", "workers", "gdal_cache_mb",
}


@dataclass(frozen=True)
class ServerConfig:
    work_dir: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "atap-jobs"
    )
    max_upload_mb: int = 1024
    max_concurrent: int = 1
    job_ttl_hours: float = 24
    grace_seconds: float = 30
    cors_origin: str | None = None

    def __post_init__(self) -> None:
        if self.max_upload_mb < 1 or self.max_concurrent < 1:
            raise ValueError("Upload and concurrency limits must be positive.")
        if self.job_ttl_hours <= 0 or self.grace_seconds < 0:
            raise ValueError("TTL must be positive and grace seconds cannot be negative.")


@dataclass
class Job:
    job_id: str
    directory: Path
    footprint_count: int
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    process: subprocess.Popen[str] | None = None
    cancel_requested: bool = False


def _validate_params(raw: str) -> dict[str, Any]:
    try:
        params = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"params must be valid JSON: {exc.msg}") from exc
    if not isinstance(params, dict):
        raise HTTPException(422, "params must be a JSON object")
    unknown = sorted(set(params) - PARAMETERS)
    if unknown:
        raise HTTPException(422, f"Unknown parameter(s): {', '.join(unknown)}")
    integer_ranges = {
        "max_height_classes": (1, 32),
        "morph_closing_iters": (0, 100),
        "round_digits": (0, 15),
        "workers": (0, 256),
        "gdal_cache_mb": (1, 65536),
    }
    ratio_fields = {
        "min_footprint_change_ratio", "parent_min_containment_ratio",
        "rectangular_ratio", "circularity_threshold",
    }
    nonnegative = {
        "height_diff_threshold_m", "min_subregion_area_m2",
        "min_building_height_m", "max_fill_hole_area_m2",
        "simplify_tolerance_m",
    }
    for key, value in params.items():
        if key == "regularize" and not isinstance(value, bool):
            raise HTTPException(422, f"{key} must be a boolean")
        if (
            key in integer_ranges
            and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not integer_ranges[key][0] <= value <= integer_ranges[key][1]
            )
        ):
            low, high = integer_ranges[key]
            raise HTTPException(422, f"{key} must be an integer from {low} to {high}")
        if (
            key in ratio_fields
            and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0 <= value <= 1
            )
        ):
            raise HTTPException(422, f"{key} must be between 0 and 1")
        if (
            key in nonnegative
            and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            )
        ):
            raise HTTPException(422, f"{key} must be non-negative")
    if params.get("base_elevation_stat") not in (None, "min", "mean", "median"):
        raise HTTPException(422, "base_elevation_stat is invalid")
    if params.get("ground_source_type") not in (None, "DTM", "DEM"):
        raise HTTPException(422, "ground_source_type is invalid")
    keep = params.get("keep_properties")
    if keep is not None and (
        not isinstance(keep, list)
        or not all(isinstance(value, str) for value in keep)
    ):
        raise HTTPException(422, "keep_properties must be an array of strings")
    for key in ("id_field", "vertical_datum"):
        value = params.get(key)
        if value is not None and not isinstance(value, str):
            raise HTTPException(422, f"{key} must be a string or null")
    if "working_crs" in params and not isinstance(params["working_crs"], str):
        raise HTTPException(422, "working_crs must be a string")
    return params


def _read_footprints(path: Path) -> int:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"Invalid footprint GeoJSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise HTTPException(422, "Footprint GeoJSON must be a FeatureCollection")
    features = doc.get("features")
    if not isinstance(features, list) or not features:
        raise HTTPException(422, "Footprint GeoJSON must contain features")
    if len(features) > MAX_FOOTPRINTS:
        raise HTTPException(422, "Footprint feature limit exceeded")
    return len(features)


class JobManager:
    def __init__(
        self,
        config: ServerConfig,
        command_builder: Callable[[Job], list[str]] | None = None,
    ):
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.queue: deque[str] = deque()
        self.running: set[str] = set()
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.command_builder = command_builder or self._default_command
        self.cleanup_expired()
        self.cleaner = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleaner.start()

    def _default_command(self, job: Job) -> list[str]:
        directory = job.directory
        return [
            sys.executable, "-m", "atap", "run",
            "--input-geojson", str(directory / "footprint.geojson"),
            "--dsm", str(directory / "dsm.tif"),
            "--dtm", str(directory / "dtm.tif"),
            "--output", str(directory / "output.geojson"),
            "--params-json", str(directory / "params.json"),
            "--events", "jsonl",
            "--cancel-file", str(directory / "CANCEL"),
            "--raster-drivers", "GTiff",
        ]

    def submit(self, directory: Path, footprint_count: int) -> Job:
        job = Job(directory.name, directory, footprint_count)
        with self.lock:
            self.jobs[job.job_id] = job
            self.queue.append(job.job_id)
            if len(self.running) >= self.config.max_concurrent:
                self._event(job, {"type": "queued", "position": len(self.queue)})
            self._pump()
        return job

    @staticmethod
    def _event(job: Job, event: dict[str, Any]) -> None:
        job.events.append(event)

    def _pump(self) -> None:
        while self.queue and len(self.running) < self.config.max_concurrent:
            job = self.jobs[self.queue.popleft()]
            self.running.add(job.job_id)
            threading.Thread(target=self._run, args=(job,), daemon=True).start()
        for position, job_id in enumerate(self.queue, 1):
            job = self.jobs[job_id]
            event = {"type": "queued", "position": position}
            if not job.events or job.events[-1] != event:
                self._event(job, event)

    def _run(self, job: Job) -> None:
        with self.lock:
            if job.cancel_requested:
                self._finish(job, "cancelled", {"type": "cancelled"})
                return
            job.status = "running"
            job.started_at = time.time()
            self._event(job, {"type": "started"})
        process_options: dict[str, Any]
        if os.name == "nt":
            process_options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            process_options = {"start_new_session": True}
        with (job.directory / "run.log").open("a", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    self.command_builder(job),
                    stdout=subprocess.PIPE,
                    stderr=log,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **process_options,
                )
                with self.lock:
                    job.process = process
                    cancel_pending = job.cancel_requested
                if cancel_pending:
                    threading.Thread(
                        target=self._force_cancel, args=(process,), daemon=True
                    ).start()
                assert process.stdout is not None
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = {
                            "type": "log", "level": "warn",
                            "message": line.rstrip(),
                        }
                    with self.lock:
                        if event.get("type") == "progress":
                            job.progress = event
                        elif event.get("type") == "result":
                            job.result = {
                                key: event.get(key)
                                for key in (
                                    "num_features", "num_buildings",
                                    "num_skipped",
                                )
                            }
                        elif event.get("type") == "error":
                            job.error = {
                                "code": event.get("code", "INTERNAL"),
                                "message": event.get("message", "Job failed"),
                            }
                        self._event(job, event)
                code = process.wait()
            except Exception as exc:
                code = 4
                with self.lock:
                    job.error = {"code": "INTERNAL", "message": str(exc)}
        with self.lock:
            if job.cancel_requested or code == 130:
                self._finish(job, "cancelled", {"type": "cancelled"})
            elif code == 0 and job.result is not None:
                self._finish(
                    job, "completed",
                    {"type": "completed", "result": job.result},
                )
            else:
                error = job.error or {
                    "code": "INTERNAL",
                    "message": f"CLI exited with status {code}",
                }
                self._finish(
                    job, "failed",
                    {"type": "failed", "error": error["message"]},
                )

    def _finish(self, job: Job, status: str, event: dict[str, Any]) -> None:
        job.status = status
        job.finished_at = time.time()
        job.process = None
        self.running.discard(job.job_id)
        self._event(job, event)
        self._event(job, {"type": "close"})
        self._pump()

    def cancel(self, job: Job) -> None:
        with self.lock:
            if job.status in TERMINAL_STATES:
                return
            job.cancel_requested = True
            (job.directory / "CANCEL").touch()
            if job.status == "queued":
                try:
                    self.queue.remove(job.job_id)
                except ValueError:
                    pass
                self._finish(job, "cancelled", {"type": "cancelled"})
                return
            job.status = "cancelling"
            self._event(job, {"type": "cancelling"})
            process = job.process
        if process is not None:
            threading.Thread(
                target=self._force_cancel, args=(process,), daemon=True
            ).start()

    def _force_cancel(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=self.config.grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def snapshot(self, job: Job) -> dict[str, Any]:
        with self.lock:
            position = (
                list(self.queue).index(job.job_id) + 1
                if job.job_id in self.queue else 0
            )
            data: dict[str, Any] = {"status": job.status}
            if position:
                data["queue_position"] = position
            if job.result is not None:
                data["result"] = job.result
            if job.error is not None:
                data["error"] = job.error["message"]
            return data

    def cleanup_expired(self) -> None:
        cutoff = time.time() - self.config.job_ttl_hours * 3600
        for directory in self.config.work_dir.iterdir():
            if not directory.is_dir() or directory.stat().st_mtime >= cutoff:
                continue
            try:
                uuid.UUID(directory.name)
            except ValueError:
                continue
            with self.lock:
                job = self.jobs.get(directory.name)
                if job is not None and job.status not in TERMINAL_STATES:
                    continue
            if directory.resolve().parent == self.config.work_dir.resolve():
                shutil.rmtree(directory)
                with self.lock:
                    self.jobs.pop(directory.name, None)

    def _cleanup_loop(self) -> None:
        while not self.stopping.wait(3600):
            self.cleanup_expired()

    def close(self) -> None:
        self.stopping.set()
        with self.lock:
            active = [self.jobs[job_id] for job_id in self.running]
        for job in active:
            self.cancel(job)
        for job in active:
            if job.process is not None:
                self._force_cancel(job.process)


def create_app(
    config: ServerConfig | None = None,
    manager: JobManager | None = None,
) -> FastAPI:
    config = config or ServerConfig()
    manager = manager or JobManager(config)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        manager.close()

    app = FastAPI(
        title="ATAP local server", version=__version__, lifespan=lifespan
    )
    app.state.manager = manager
    if config.cors_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[config.cors_origin],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    static = Path(__file__).parent / "static"
    app.mount(
        "/vendor",
        StaticFiles(directory=static / "vendor", check_dir=False),
        name="vendor",
    )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with manager.lock:
            return {
                "version": __version__,
                "source_url": SOURCE_URL,
                "running_jobs": len(manager.running),
                "queued_jobs": len(manager.queue),
                "max_concurrent": config.max_concurrent,
                "max_upload_mb": config.max_upload_mb,
            }

    @app.post("/api/jobs")
    async def create_job(
        footprint: UploadFile = File(...),
        dsm: UploadFile = File(...),
        dtm: UploadFile = File(...),
        params: str = Form("{}"),
    ) -> JSONResponse:
        parsed = _validate_params(params)
        job_id = str(uuid.uuid4())
        directory = config.work_dir / job_id
        directory.mkdir(parents=True)
        total = 0
        try:
            for upload, name in (
                (footprint, "footprint.geojson"),
                (dsm, "dsm.tif"),
                (dtm, "dtm.tif"),
            ):
                with (directory / name).open("wb") as target:
                    while chunk := await upload.read(UPLOAD_CHUNK):
                        total += len(chunk)
                        if total > config.max_upload_mb * 1024 * 1024:
                            raise HTTPException(413, "Upload size limit exceeded")
                        target.write(chunk)
            count = _read_footprints(directory / "footprint.geojson")
            (directory / "params.json").write_text(
                json.dumps(parsed), encoding="utf-8"
            )
            job = manager.submit(directory, count)
            return JSONResponse({
                "job_id": job.job_id,
                "footprint_count": count,
                "queue_position": manager.snapshot(job).get("queue_position", 0),
            })
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def get_job(job_id: str) -> Job:
        try:
            uuid.UUID(job_id)
            return manager.jobs[job_id]
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, "Job not found") from exc

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        return manager.snapshot(get_job(job_id))

    @app.get("/api/jobs/{job_id}/events")
    async def events(
        job_id: str, request: Request
    ) -> StreamingResponse:
        job = get_job(job_id)

        async def stream():
            cursor = 0
            while True:
                with manager.lock:
                    pending = job.events[cursor:]
                    cursor = len(job.events)
                for event in pending:
                    yield f"data: {json.dumps(event)}\n\n"
                    if event["type"] == "close":
                        return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(0.1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        job = get_job(job_id)
        manager.cancel(job)
        return manager.snapshot(job)

    @app.get("/api/jobs/{job_id}/artifacts/{kind}")
    def artifact(job_id: str, kind: str) -> FileResponse:
        names = {"output": "output.geojson", "log": "run.log"}
        if kind not in names:
            raise HTTPException(404, "Artifact not found")
        name = names[kind]
        path = get_job(job_id).directory / name
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")
        media_type = "application/geo+json" if kind == "output" else "text/plain"
        return FileResponse(path, filename=name, media_type=media_type)

    return app


def serve(args: Any) -> int:
    import uvicorn

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        warnings.warn(
            "ATAP has no authentication; exposing it beyond localhost is unsafe.",
            stacklevel=1,
        )
    config = ServerConfig(
        work_dir=args.work_dir or Path(tempfile.gettempdir()) / "atap-jobs",
        max_upload_mb=args.max_upload_mb,
        max_concurrent=args.max_concurrent,
        job_ttl_hours=args.job_ttl_hours,
        grace_seconds=args.grace_seconds,
        cors_origin=args.cors_origin,
    )
    uvicorn.run(create_app(config), host=args.host, port=args.port)
    return 0
