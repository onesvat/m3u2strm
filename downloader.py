"""Downloader for m3u2strm — downloads .mkv files from .strm URLs.

Single-threaded sequential download queue. Reads URLs from .strm files,
follows 302 redirects to CDN, downloads with resume support.
On completion: deletes .strm, keeps .mkv.
"""

import os
import time
import logging
import threading
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MAX_RETRIES = 5
RETRY_DELAY = 10  # seconds between retries
SPEED_LIMIT_KBPS = None  # no limit by default, set to throttle


class DownloadItem:
    """A single download item with state tracking."""

    def __init__(self, strm_path: str, mkv_path: str, url: str):
        self.strm_path = strm_path
        self.mkv_path = mkv_path
        self.url = url
        self.part_path = mkv_path + ".part"
        self.status: str = "queued"          # queued | downloading | done | failed
        self.downloaded: int = 0
        self.total: int = 0
        self.error: str | None = None
        self.speed: float = 0.0
        self.display_name = os.path.basename(mkv_path).replace(".mkv", "")


class DownloadQueue:
    """Thread-safe single-item-at-a-time download queue."""

    def __init__(self):
        self._lock = threading.Lock()
        self._queue: list[DownloadItem] = []
        self._current: DownloadItem | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def current(self) -> DownloadItem | None:
        return self._current

    @property
    def queue(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._queue)

    @property
    def running(self) -> bool:
        return self._running

    def enqueue(self, item: DownloadItem):
        with self._lock:
            # Avoid duplicates
            for existing in self._queue:
                if existing.mkv_path == item.mkv_path:
                    return
            if self._current and self._current.mkv_path == item.mkv_path:
                return
            self._queue.append(item)
            logger.info(f"Enqueued: {item.display_name}")

    def _pop_next(self) -> DownloadItem | None:
        with self._lock:
            if self._queue:
                return self._queue.pop(0)
            return None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        logger.info("Download queue worker started")

    def _worker(self):
        while self._running:
            item = self._pop_next()
            if item is None:
                time.sleep(5)
                continue

            self._current = item
            self._download_one(item)
            self._current = None

    def _download_one(self, item: DownloadItem):
        """Download a single item with retry logic."""
        item.status = "downloading"

        # Check if .mkv already exists (already downloaded)
        if os.path.exists(item.mkv_path):
            mkv_size = os.path.getsize(item.mkv_path)
            if mkv_size > 0:
                logger.info(f"Already downloaded: {item.display_name} ({mkv_size} bytes)")
                item.status = "done"
                self._cleanup_strm(item)
                return
            else:
                os.remove(item.mkv_path)

        # Check for partial download
        if os.path.exists(item.part_path):
            item.downloaded = os.path.getsize(item.part_path)
            logger.info(f"Resuming from {item.downloaded} bytes: {item.display_name}")
        else:
            item.downloaded = 0

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._do_download(item, attempt)
                # Success
                item.status = "done"
                self._cleanup_strm(item)
                logger.info(f"Downloaded: {item.display_name} ({item.total} bytes)")
                return
            except requests.exceptions.RequestException as e:
                item.error = str(e)
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                else:
                    item.status = "failed"
                    logger.error(f"Failed after {MAX_RETRIES} attempts: {item.display_name}")

    def _do_download(self, item: DownloadItem, attempt: int):
        """Core download logic — GET with redirect, Range header for resume."""
        session = requests.Session()

        # First request: gateway URL → 302 → CDN URL with token
        headers = {}
        if item.downloaded > 0:
            headers["Range"] = f"bytes={item.downloaded}-"

        resp = session.get(item.url, headers=headers, stream=True, timeout=30)

        if resp.status_code == 302:
            # Gateway redirect — follow to CDN
            cdn_url = resp.headers["Location"]
            resp.close()
            # Re-request on CDN with the same headers
            resp = session.get(cdn_url, headers=headers, stream=True, timeout=60)

        if resp.status_code == 416:
            # Range Not Satisfiable — file might be complete already
            resp.close()
            part_size = os.path.getsize(item.part_path)
            if part_size > 0:
                os.rename(item.part_path, item.mkv_path)
                item.total = part_size
                return
            raise requests.exceptions.RequestException("HTTP 416 with zero partial")

        if resp.status_code not in (200, 206):
            resp.close()
            raise requests.exceptions.RequestException(
                f"HTTP {resp.status_code} from CDN"
            )

        # Determine total size
        if "Content-Range" in resp.headers:
            # "bytes X-Y/Z" → Z is total
            item.total = int(resp.headers["Content-Range"].split("/")[-1])
        elif "Content-Length" in resp.headers:
            item.total = int(resp.headers["Content-Length"])
        else:
            item.total = 0  # unknown

        # Open file for append (resume) or write
        mode = "ab" if item.downloaded > 0 and resp.status_code == 206 else "wb"
        start_time = time.time()
        last_log = start_time

        with open(item.part_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
                    item.downloaded += len(chunk)

                    # Speed limiting
                    if SPEED_LIMIT_KBPS:
                        elapsed = time.time() - start_time
                        target_bytes = elapsed * (SPEED_LIMIT_KBPS * 1024)
                        if item.downloaded > target_bytes:
                            sleep_time = (
                                item.downloaded - target_bytes
                            ) / (SPEED_LIMIT_KBPS * 1024)
                            time.sleep(sleep_time)

                    # Log progress every 30s
                    now = time.time()
                    if now - last_log >= 30:
                        item.speed = item.downloaded / (now - start_time)
                        pct = (
                            f"{item.downloaded / item.total * 100:.0f}%"
                            if item.total
                            else "?"
                        )
                        logger.info(
                            f"{item.display_name}: {pct} "
                            f"({item.downloaded / 1024 / 1024:.0f}MB"
                            + (
                                f"/{item.total / 1024 / 1024:.0f}MB"
                                if item.total
                                else ""
                            )
                            + f", {item.speed / 1024:.0f} KB/s)"
                        )
                        last_log = now

        resp.close()

        # Verify file size if total known
        if item.total > 0 and os.path.getsize(item.part_path) < item.total:
            raise requests.exceptions.RequestException(
                f"Incomplete download: {os.path.getsize(item.part_path)}/{item.total}"
            )

        # Atomic rename
        os.rename(item.part_path, item.mkv_path)

    def _cleanup_strm(self, item: DownloadItem):
        """Delete the .strm file after successful download."""
        try:
            if os.path.exists(item.strm_path):
                os.remove(item.strm_path)
                logger.debug(f"Removed strm: {item.strm_path}")
        except OSError as e:
            logger.warning(f"Failed to remove strm {item.strm_path}: {e}")

    def get_status(self) -> dict:
        """Return full status for API."""
        current = None
        if self._current:
            current = {
                "display_name": self._current.display_name,
                "status": self._current.status,
                "downloaded": self._current.downloaded,
                "total": self._current.total,
                "speed": self._current.speed,
                "error": self._current.error,
            }
        queue_list = [
            {
                "display_name": q.display_name,
                "status": q.status,
            }
            for q in self._queue
        ]
        return {"current": current, "queue": queue_list, "running": self._running}


# Global instance
_queue = DownloadQueue()


def enqueue_download(strm_path: str, mkv_path: str, url: str):
    """Add a download to the queue."""
    item = DownloadItem(strm_path, mkv_path, url)
    _queue.enqueue(item)
    _queue.start()


def get_status() -> dict:
    return _queue.get_status()


def find_strm_files(vods_dir: str) -> list[str]:
    """Find all .strm files under vods_dir."""
    strm_files = []
    for root, _, files in os.walk(vods_dir):
        for f in files:
            if f.endswith(".strm"):
                strm_files.append(os.path.join(root, f))
    return strm_files


def read_strm_url(strm_path: str) -> str | None:
    """Read URL from .strm file."""
    try:
        with open(strm_path, "r") as f:
            return f.read().strip()
    except OSError as e:
        logger.error(f"Failed to read {strm_path}: {e}")
        return None


def scan_and_enqueue(vods_dir: str, download_filters: list[str]):
    """Scan .strm files, enqueue those matching download filters.

    download_filters: list of series/movie names to download.
    """
    strm_files = find_strm_files(vods_dir)
    count = 0

    for strm_path in strm_files:
        # Determine if this belongs to a download-filtered series/movie
        rel = os.path.relpath(strm_path, vods_dir)
        parts = Path(rel).parts

        if not parts:
            continue

        name = None
        if parts[0] == "series" and len(parts) >= 2:
            name = parts[1]
        elif parts[0] == "movies" and len(parts) >= 2:
            name = parts[1]
        else:
            continue

        # Check against download filters
        if not download_filters:
            continue

        matched = False
        for f in download_filters:
            if f.lower() in name.lower():
                matched = True
                break

        if not matched:
            continue

        url = read_strm_url(strm_path)
        if not url:
            continue

        mkv_path = strm_path.replace(".strm", ".mkv")

        # Skip if .mkv already exists (already downloaded)
        if os.path.exists(mkv_path):
            continue

        enqueue_download(strm_path, mkv_path, url)
        count += 1

    if count:
        logger.info(f"Enqueued {count} items for download")
    return count
