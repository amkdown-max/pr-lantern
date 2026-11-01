"""Versioned, atomic snapshot storage. No authentication data is stored."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .core import parse_pr_url, parse_time


@contextmanager
def state_lock(path):
    """Exclude overlapping writers; the OS releases the lock after a crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError(
                    "Another check is using this state file; retry when it ends."
                ) from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(
                    "Another check is using this state file; retry when it ends."
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def load_state(path):
    path = Path(path)
    if not path.exists():
        return {"version": 1, "snapshots": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("snapshots"), dict):
            raise ValueError("Unsupported snapshot format or version")
        for url, snapshot in data["snapshots"].items():
            if parse_pr_url(url) != url or snapshot["url"] != url:
                raise ValueError("Invalid snapshot URL")
            for key in ("state", "review", "head", "title"):
                if not isinstance(snapshot[key], str):
                    raise ValueError(f"Invalid snapshot field: {key}")
            if snapshot["state"] not in {"OPEN", "CLOSED", "MERGED"}:
                raise ValueError("Invalid PR state")
            if not isinstance(snapshot["draft"], bool):
                raise ValueError("Invalid draft flag")
            parse_time(snapshot["created_at"])
            parse_time(snapshot["last_feedback_at"])
            if not isinstance(snapshot["feedback"], dict):
                raise ValueError("Invalid feedback history")
            for identifier, timestamp in snapshot["feedback"].items():
                if not isinstance(identifier, str) or not isinstance(timestamp, str):
                    raise ValueError("Invalid feedback entry")
                parse_time(timestamp)
            if not isinstance(snapshot["checks"], dict):
                raise ValueError("Invalid check summary")
            checks = snapshot["checks"]
            keys = ("passed", "failed", "pending", "action_required", "skipped")
            if checks["state"] not in {"none", "passed", "failed", "pending", "action_required"}:
                raise ValueError("Invalid check state")
            if any(type(checks[key]) is not int or checks[key] < 0 for key in (*keys, "total")):
                raise ValueError("Invalid check counts")
            if checks["total"] != sum(checks[key] for key in keys):
                raise ValueError("Inconsistent check counts")
        return data
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Cannot read snapshot {path}: {exc}. File left unchanged.") from exc


def save_state(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".lantern-", delete=False
        ) as stream:
            temporary = stream.name
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
