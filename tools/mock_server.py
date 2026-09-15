# SPDX-License-Identifier: AGPL-3.0-only
"""
Local stand-in for `atap serve`, implementing the API contract written at
the top of playground/index.html with the packaged engine running in a
thread. Stdlib only. NOT the production server: no security hardening, no TTL
cleanup, no subprocess isolation. Uploads are held in memory while parsed,
so very large rasters need RAM of roughly 2-3x their size.

    python mock_server.py [PORT]

Environment:
    MOCK_MAX_UPLOAD_MB   upload limit reported to the browser (default 2048)
    MOCK_DELAY           seconds to wait before each job starts (tests only)
"""
import email.parser
import email.policy
import json
import os
import queue
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# Import the package by module name so spawned workers can re-import it.
import atap as E  # noqa: E402
from atap.engine.config import ENGINE_VERSION  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, "..", "src", "atap", "server", "static"))
WORK = None  # created in main(); spawn workers import this module too
MAX_UPLOAD_MB = int(os.environ.get("MOCK_MAX_UPLOAD_MB", "2048"))
JOBS = {}; Q = []; LOCK = threading.Lock(); DELAY = float(os.environ.get("MOCK_DELAY", "0"))

def emit(job, ev):
    job["events"].append(ev)
    for q in list(job["subs"]): q.put(ev)

def worker():
    while True:
        job = None
        with LOCK:
            if Q and not any(j["status"] == "running" for j in JOBS.values()):
                job = Q.pop(0); job["status"] = "running"
                for i, j in enumerate(Q): emit(j, {"type": "queued", "position": i + 1})
        if not job: time.sleep(0.1); continue
        emit(job, {"type": "started"}); time.sleep(DELAY)
        d = job["dir"]; logf = open(os.path.join(d, "run.log"), "w")
        def log(m): logf.write(m + "\n"); emit(job, {"type": "log", "message": m})
        def prog(c, t, m): emit(job, {"type": "progress", "current": c, "total": t, "message": m})
        try:
            params = job["params"]
            r = E.run_elevation(os.path.join(d, "footprint.geojson"), os.path.join(d, "dtm.tif"),
                                os.path.join(d, "dsm.tif"), os.path.join(d, "output.geojson"),
                                progress_cb=prog, log_cb=log, cancel_flag=lambda: job["cancel"], **params)
            if r["cancelled"]: job["status"] = "cancelled"; emit(job, {"type": "cancelled"})
            else: job["status"] = "completed"; job["result"] = r; emit(job, {"type": "completed", "result": {k: r[k] for k in ("num_features", "num_buildings", "num_skipped")}})
        except Exception as e:
            job["status"] = "failed"; job["error"] = str(e); emit(job, {"type": "failed", "error": str(e)})
        logf.close(); emit(job, {"type": "close"})

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj=None, ctype="application/json", body=None):
        b = body if body is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/health":
            with LOCK: return self.send(200, {"version": ENGINE_VERSION, "source_url": "https://github.com/enygma-id/atap",
                "running_jobs": sum(j["status"] == "running" for j in JOBS.values()), "queued_jobs": len(Q), "max_concurrent": 1, "max_upload_mb": MAX_UPLOAD_MB})
        if p.startswith("/api/jobs/"):
            parts = p.split("/"); job = JOBS.get(parts[3])
            if not job: return self.send(404, {"detail": "unknown job"})
            if len(parts) == 4: return self.send(200, {"status": job["status"], "result": job.get("result"), "error": job.get("error")})
            if parts[4] == "events":
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
                q = queue.Queue()
                with LOCK: backlog = list(job["events"]); job["subs"].append(q)
                for ev in backlog: q.put(ev)
                while True:
                    ev = q.get(); self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode()); self.wfile.flush()
                    if ev["type"] == "close": return
            if parts[4] == "artifacts":
                f = {"output": "output.geojson", "log": "run.log"}.get(parts[5]); fp = os.path.join(job["dir"], f or "x")
                if not f or not os.path.exists(fp): return self.send(404, {"detail": "not found"})
                return self.send(200, ctype="application/geo+json" if f.endswith("json") else "text/plain", body=open(fp, "rb").read())
        f = "index.html" if p == "/" else p.lstrip("/")
        fp = os.path.normpath(os.path.join(ROOT, f))
        if fp.startswith(ROOT) and os.path.isfile(fp):
            return self.send(200, ctype="text/html" if fp.endswith("html") else "application/javascript", body=open(fp, "rb").read())
        self.send(404, {"detail": "not found"})
    def do_POST(self):
        p = self.path
        if p == "/api/jobs":
            n = int(self.headers["Content-Length"]); raw = self.rfile.read(n)
            msg = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + raw)
            fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in msg.iter_parts()}
            for k in ("footprint", "dsm", "dtm"):
                if k not in fields: return self.send(422, {"detail": f"missing file: {k}"})
            jid = uuid.uuid4().hex[:12]; d = os.path.join(WORK, jid); os.makedirs(d)
            for k, name in (("footprint", "footprint.geojson"), ("dsm", "dsm.tif"), ("dtm", "dtm.tif")): open(os.path.join(d, name), "wb").write(fields[k])
            params = json.loads(fields.get("params", b"{}"))
            fc = json.loads(fields["footprint"]); count = len(fc.get("features", []))
            with LOCK:
                job = {"id": jid, "dir": d, "params": params, "status": "queued", "cancel": False, "events": [], "subs": []}
                JOBS[jid] = job; Q.append(job)
                pos = Q.index(job) + (1 if any(j["status"] == "running" for j in JOBS.values()) else 0)
            if pos > 0: emit(job, {"type": "queued", "position": pos})
            return self.send(200, {"job_id": jid, "footprint_count": count, "queue_position": pos})
        if p.endswith("/cancel"):
            job = JOBS.get(p.split("/")[3])
            if not job: return self.send(404, {"detail": "unknown job"})
            job["cancel"] = True
            if job["status"] == "queued":
                with LOCK: Q.remove(job)
                job["status"] = "cancelled"; emit(job, {"type": "cancelled"}); emit(job, {"type": "close"})
            else: emit(job, {"type": "cancelling"})
            return self.send(200, {"ok": True})
        self.send(404, {"detail": "not found"})

def main():
    global WORK
    WORK = tempfile.mkdtemp(prefix="atap_jobs_")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    threading.Thread(target=worker, daemon=True).start()
    print(f"ATAP playground (mock server): http://127.0.0.1:{port}/   jobs in {WORK}   upload limit {MAX_UPLOAD_MB} MB")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":   # required: spawn workers import this module
    main()
