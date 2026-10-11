"""Health state shared by the task loop, the web UI and the downloader.

task.py runs as __main__ while web_ui imports it again as "task", so state
kept in task.py would be split in two; this module is imported once.
Exposed as /api/status for monitoring (e.g. a Home Assistant REST sensor).
"""

import logging
import os
import re
import threading
import time
from collections import deque

LOG_LINES = 30
FAILED_DOWNLOAD_WINDOW = 24 * 3600

_lock = threading.Lock()
_events = {}
_logs = deque(maxlen=LOG_LINES)

_SECRETS = [
    (re.compile(r"(username|password)=[^&\s'\"]+"), r"\1=***"),
    (re.compile(r"/(series|movie|live)/[^/\s]+/[^/\s]+/"), r"/\1/***/***/"),
    (re.compile(r"(bot)\d+:[\w-]+"), r"\1***"),
]


def mask(text):
    """Hide provider credentials and bot tokens in log text."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


def record(name, ok, error=None, **details):
    """Remember the latest outcome of an operation (playlist, run, jellyfin, telegram)."""
    now = time.time()
    with _lock:
        event = _events.setdefault(name, {"last_success": None})
        event.update(details)
        event["last_attempt"] = now
        event["ok"] = ok
        if ok:
            event["last_success"] = now
            event["error"] = None
        else:
            event["error"] = mask(str(error)) if error else "failed"


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)) if ts else None


class _MaskFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        masked = mask(message)
        if masked != message:
            record.msg, record.args = masked, ()
        return True


class _RecentHandler(logging.Handler):
    def emit(self, record):
        _logs.append({
            "time": _iso(record.created),
            "level": record.levelname,
            "source": record.name,
            "message": mask(record.getMessage())[:300],
        })


def install_logging():
    """Mask credentials in all log output and keep recent warnings/errors."""
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(_MaskFilter())
    recent = _RecentHandler(level=logging.WARNING)
    root.addHandler(recent)


def snapshot(downloads):
    """Status document with a list of current problems."""
    interval = int(os.getenv("TASK_INTERVAL", 5)) * 60
    now = time.time()
    with _lock:
        events = {name: dict(event) for name, event in _events.items()}
        logs = list(_logs)[::-1]

    problems = []
    playlist = events.get("playlist")
    if playlist:
        last = playlist.get("last_success")
        # Allow a couple of failed runs before calling the playlist stale
        if last is None or now - last > max(3 * interval, 2 * 3600):
            since = _iso(last) or "never"
            problems.append(f"Playlist not updated since {since}: {playlist.get('error')}")
    run = events.get("run")
    if run and not run["ok"]:
        problems.append(f"Last run failed: {run['error']}")
    jellyfin = events.get("jellyfin")
    if jellyfin and not jellyfin["ok"]:
        problems.append(f"Jellyfin refresh failed: {jellyfin['error']}")

    failed = [h for h in downloads["history"]
              if h["result"] == "failed" and now - h["ts"] < FAILED_DOWNLOAD_WINDOW]
    done = [h for h in downloads["history"]
            if h["result"] == "done" and now - h["ts"] < FAILED_DOWNLOAD_WINDOW]
    if failed:
        names = ", ".join(h["display_name"] for h in failed[:3])
        problems.append(f"{len(failed)} download(s) failed in 24h: {names} ({failed[0].get('error')})")
    if downloads["state"].startswith("paused: only"):
        problems.append(f"Downloads {downloads['state']}")

    current = downloads["current"]
    percent = None
    if current and current["total"]:
        percent = round(current["downloaded"] / current["total"] * 100, 1)

    for event in events.values():
        for key in ("last_attempt", "last_success"):
            event[key] = _iso(event.get(key))

    history = [dict(h, error=mask(h["error"]) if h.get("error") else None)
               for h in downloads["history"][:10]]

    return {
        "ok": not problems,
        "problems": [mask(p) for p in problems],
        "events": events,
        "downloads": {
            "state": downloads["state"],
            "current": current["display_name"] if current else None,
            "percent": percent,
            "speed_mb_s": round(current["speed"] / 1024 ** 2, 1) if current else None,
            "queue": len(downloads["queue"]),
            "next": downloads["queue"][:5],
            "done_24h": len(done),
            "failed_24h": len(failed),
            "history": history,
        },
        "logs": logs,
    }
