"""Download queue for m3u2strm: turns selected .strm entries into local files.

One file at a time, because IPTV accounts usually allow a single connection.
Downloads go to "<name>.<ext>.part" and are resumed with Range requests; on
success the file is renamed and the matching .strm is removed. The worker
pauses (keeping the .part file) outside DOWNLOAD_HOURS, when free disk space
is low, or when the busy check reports that someone else needs the
connection (e.g. Jellyfin is playing a stream).
"""

import os
import shutil
import threading
import time
import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = (".mkv", ".mp4", ".avi", ".ts", ".m4v")
CHUNK_SIZE = 1024 * 1024
CHECK_INTERVAL = 15  # seconds between pause checks while downloading
IDLE_INTERVAL = 30  # seconds between checks while waiting
MAX_ATTEMPTS = 5
RETRY_DELAY = 30
FAILED_BACKOFF = 60 * 60  # skip a failed file for an hour
HISTORY_SIZE = 20


def media_extension(url):
    """Container extension from the stream URL, defaulting to .mkv."""
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in VIDEO_EXTENSIONS else ".mkv"


def downloaded_file_for(strm_path):
    """Return the downloaded media file next to a .strm path, if any."""
    stem = os.path.splitext(strm_path)[0]
    for ext in VIDEO_EXTENSIONS:
        if os.path.exists(stem + ext):
            return stem + ext
    return None


def parse_hours(value):
    """Parse "HH-HH" (end exclusive, may wrap midnight). Empty = always."""
    value = (value or "").strip()
    if not value:
        return None
    start, end = value.split("-")
    return int(start) % 24, int(end) % 24


def in_window(hours, now=None):
    if hours is None:
        return True
    start, end = hours
    hour = (now or time.localtime()).tm_hour
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class Job:
    def __init__(self, strm_path, url, display_name):
        self.strm_path = strm_path
        self.url = url
        self.display_name = display_name
        self.target_path = os.path.splitext(strm_path)[0] + media_extension(url)
        self.part_path = self.target_path + ".part"
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0

    def to_dict(self):
        return {
            "display_name": self.display_name,
            "downloaded": self.downloaded,
            "total": self.total,
            "speed": self.speed,
        }


class Paused(Exception):
    pass


class Cancelled(Exception):
    pass


class DownloadQueue:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._queue = []
        self._current = None
        self._cancel_current = False
        self._failed_until = {}
        self._history = []
        self._completed_batch = []
        self._state = "idle"
        self._thread = None

        self.user_agent = "VLC/3.0.20 LibVLC/3.0.20"
        self.hours = None
        self.min_free_bytes = 0
        self.speed_limit = 0  # bytes per second, 0 = unlimited
        self.busy_check = None  # callable(downloading) -> reason string or None
        self.on_batch_done = None  # callable(list of display names)

    def configure(self, user_agent=None, hours="", min_free_gb=20,
                  speed_limit_kbps=0, busy_check=None, on_batch_done=None):
        if user_agent:
            self.user_agent = user_agent
        self.hours = parse_hours(hours)
        self.min_free_bytes = int(float(min_free_gb) * 1024 ** 3)
        self.speed_limit = int(float(speed_limit_kbps) * 1024)
        self.busy_check = busy_check
        self.on_batch_done = on_batch_done

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        logger.info("Download worker started")

    def sync(self, jobs):
        """Replace the pending queue with jobs; cancel the current one if it was dropped."""
        now = time.time()
        pending = []
        seen = set()
        for job in jobs:
            if job.target_path in seen or os.path.exists(job.target_path):
                continue
            if self._failed_until.get(job.target_path, 0) > now:
                continue
            seen.add(job.target_path)
            pending.append(job)

        with self._lock:
            current = self._current
            if current is not None:
                if current.target_path in seen:
                    pending = [j for j in pending if j.target_path != current.target_path]
                else:
                    self._cancel_current = True
            self._queue = pending

        if pending:
            logger.info(f"Download queue: {len(pending)} pending")
        self._wake.set()
        return len(pending)

    def status(self):
        with self._lock:
            return {
                "state": self._state,
                "current": self._current.to_dict() if self._current else None,
                "queue": [j.display_name for j in self._queue],
                "history": list(self._history),
            }

    # --- worker ---

    def _set_state(self, state):
        if state != self._state:
            logger.info(f"Download worker: {state}")
        self._state = state

    def _blocked_reason(self, job, downloading=False):
        if not in_window(self.hours):
            start, end = self.hours
            return f"waiting for download hours {start:02d}-{end:02d}"
        free = shutil.disk_usage(os.path.dirname(job.target_path)).free
        if free < self.min_free_bytes:
            return f"paused: only {free / 1024 ** 3:.0f} GB free"
        if self.busy_check:
            try:
                reason = self.busy_check(downloading)
            except Exception as e:
                # Do not block downloads forever because Jellyfin/provider is unreachable
                logger.warning(f"Busy check failed, continuing: {e}")
                reason = None
            if reason:
                return f"paused: {reason}"
        return None

    def _next_job(self):
        with self._lock:
            if self._queue:
                self._current = self._queue.pop(0)
                self._cancel_current = False
                return self._current
            return None

    def _finish_batch_if_idle(self):
        with self._lock:
            if self._queue or not self._completed_batch:
                return
            batch, self._completed_batch = self._completed_batch, []
        if self.on_batch_done:
            try:
                self.on_batch_done(batch)
            except Exception as e:
                logger.error(f"Download completion hook failed: {e}")

    def _record(self, job, result, error=None):
        with self._lock:
            self._history.insert(0, {
                "display_name": job.display_name,
                "result": result,
                "error": error,
                "time": time.strftime("%Y-%m-%d %H:%M"),
                "ts": time.time(),
            })
            del self._history[HISTORY_SIZE:]
            if result == "done":
                self._completed_batch.append(job.display_name)

    def _worker(self):
        while True:
            job = self._next_job()
            if job is None:
                self._set_state("idle")
                self._finish_batch_if_idle()
                self._wake.wait(IDLE_INTERVAL)
                self._wake.clear()
                continue

            reason = self._blocked_reason(job)
            if reason:
                self._requeue_front(job)
                self._set_state(reason)
                self._wake.wait(IDLE_INTERVAL)
                self._wake.clear()
                continue

            self._run_job(job)
            with self._lock:
                self._current = None

    def _requeue_front(self, job):
        with self._lock:
            if not self._cancel_current:
                self._queue.insert(0, job)
            self._current = None

    def _run_job(self, job):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._set_state(f"downloading {job.display_name}")
            try:
                self._download(job)
            except Paused as e:
                logger.info(f"Paused {job.display_name}: {e}")
                self._requeue_front(job)
                return
            except Cancelled:
                logger.info(f"Cancelled {job.display_name}")
                self._remove(job.part_path)
                return
            except (requests.exceptions.RequestException, OSError) as e:
                logger.warning(f"{job.display_name}: attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_DELAY)
                    continue
                self._failed_until[job.target_path] = time.time() + FAILED_BACKOFF
                self._record(job, "failed", str(e))
                logger.error(f"Giving up on {job.display_name} for now")
                return
            else:
                self._remove(job.strm_path)
                self._record(job, "done")
                logger.info(f"Downloaded {job.display_name} ({job.total / 1024 ** 2:.0f} MB)")
                return

    def _check_pause(self, job):
        with self._lock:
            if self._cancel_current:
                raise Cancelled()
        reason = self._blocked_reason(job, downloading=True)
        if reason:
            raise Paused(reason)

    def _download(self, job):
        offset = os.path.getsize(job.part_path) if os.path.exists(job.part_path) else 0
        headers = {"User-Agent": self.user_agent}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        # requests follows the provider's 302 to the CDN and keeps the headers
        with requests.get(job.url, headers=headers, stream=True, timeout=(15, 60)) as resp:
            if resp.status_code == 416 and offset:
                # The .part file already holds the whole file
                job.total = job.downloaded = offset
                os.replace(job.part_path, job.target_path)
                return
            resp.raise_for_status()

            if resp.status_code == 206 and "Content-Range" in resp.headers:
                job.total = int(resp.headers["Content-Range"].rsplit("/", 1)[-1])
                mode = "ab"
            else:
                # Server ignored the range: start over
                offset = 0
                job.total = int(resp.headers.get("Content-Length", 0))
                mode = "wb"
            job.downloaded = offset

            start = last_check = time.time()
            received = 0
            with open(job.part_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    f.write(chunk)
                    received += len(chunk)
                    job.downloaded += len(chunk)

                    now = time.time()
                    elapsed = max(now - start, 0.001)
                    job.speed = received / elapsed
                    if self.speed_limit and job.speed > self.speed_limit:
                        time.sleep(received / self.speed_limit - elapsed)
                    if now - last_check >= CHECK_INTERVAL:
                        last_check = now
                        self._check_pause(job)

        size = os.path.getsize(job.part_path)
        if job.total and size < job.total:
            raise requests.exceptions.RequestException(f"incomplete: {size}/{job.total} bytes")
        os.replace(job.part_path, job.target_path)

    @staticmethod
    def _remove(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"Could not remove {path}: {e}")


queue = DownloadQueue()
