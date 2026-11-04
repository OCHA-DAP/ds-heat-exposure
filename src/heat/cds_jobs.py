"""Submit Copernicus CDS requests without blocking, and collect them later.

The CDS queue for derived ERA5 products can hold a request for hours, so requests are submitted
up front and their ids kept in a small JSON state file. `collect()` downloads whatever has
finished and returns the paths, so a backfill can be resumed at any time.

State file entries: name -> {dataset, request, request_id, target, status}
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ecmwf.datastores import Client

logger = logging.getLogger(__name__)

CDS_URL = "https://cds.climate.copernicus.eu/api"


def client() -> Client:
    # CDSAPI_URL in this environment points at EWDS (flood data); the key is shared across
    # the Copernicus data stores, the URL is not.
    return Client(url=CDS_URL, key=os.environ["CDSAPI_KEY"], progress=False)


class JobBook:
    def __init__(self, state_path: Path):
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs: dict = json.loads(self.path.read_text()) if self.path.exists() else {}
        self._client = None

    @property
    def c(self) -> Client:
        if self._client is None:
            self._client = client()
        return self._client

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.jobs, indent=1, sort_keys=True))
        tmp.replace(self.path)

    def submit(self, name: str, dataset: str, request: dict, target: Path, resubmit_failed=True):
        job = self.jobs.get(name)
        if job and job["status"] in ("submitted", "downloaded"):
            return job
        if job and job["status"] == "failed" and not resubmit_failed:
            return job
        remote = self.c.submit(dataset, request)
        self.jobs[name] = {
            "dataset": dataset,
            "request": request,
            "request_id": remote.request_id,
            "target": str(target),
            "status": "submitted",
        }
        self.save()
        logger.info("submitted %s -> %s", name, remote.request_id)
        return self.jobs[name]

    def collect(self, names=None) -> list[str]:
        """Download every finished request (optionally limited to `names`). Returns downloaded names.

        Holds an exclusive lock on the state file while running, so two collectors (e.g. the polling
        loop and a manual run) never download the same file into the same path at once."""
        import fcntl

        lock = open(self.path.with_suffix(".lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("another collector holds %s; skipping", self.path.name)
            lock.close()
            return []
        try:
            # re-read: another process may have updated the state since this object was created
            if self.path.exists():
                self.jobs = json.loads(self.path.read_text())
            return self._collect(names)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    def _collect(self, names=None) -> list[str]:
        done = []
        for name, job in self.jobs.items():
            if names is not None and name not in names:
                continue
            if job["status"] != "submitted":
                continue
            remote = self.c.get_remote(job["request_id"])
            status = remote.status
            if status == "successful":
                target = Path(job["target"])
                target.parent.mkdir(parents=True, exist_ok=True)
                remote.download(str(target))
                job["status"] = "downloaded"
                done.append(name)
                logger.info("downloaded %s -> %s", name, target)
                self.save()
            elif status in ("failed", "rejected", "dismissed", "deleted"):
                job["status"] = "failed"
                job["error"] = (
                    str(getattr(remote, "results", ""))[:500] if status == "failed" else status
                )
                logger.warning("%s %s", name, status)
                self.save()
        return done

    def status_counts(self) -> dict:
        out: dict = {}
        for job in self.jobs.values():
            out[job["status"]] = out.get(job["status"], 0) + 1
        return out
