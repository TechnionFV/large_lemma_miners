"""Cache helpers, including a truly immutable diskcache reader."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from diskcache import Cache, Disk
from diskcache.core import ENOVAL


class ImmutableDiskCache:
    """Minimal read-only interface for a ``diskcache.Cache`` directory.

    ``diskcache.Cache`` performs schema/settings writes while opening an
    existing cache. Replay instead connects to SQLite with ``mode=ro`` and
    ``immutable=1`` and uses diskcache's public ``Disk`` serializer only for
    key/value decoding.
    """

    def __init__(self, directory: os.PathLike[str] | str):
        self.directory = str(Path(directory).resolve())
        database = Path(self.directory) / "cache.db"
        if not database.is_file():
            raise FileNotFoundError(f"diskcache database not found: {database}")
        uri = f"file:{quote(str(database))}?mode=ro&immutable=1"
        self._connection = sqlite3.connect(uri, uri=True)
        settings = dict(
            self._connection.execute("SELECT key, value FROM Settings").fetchall()
        )
        self._disk = Disk(
            self.directory,
            min_file_size=int(settings.get("disk_min_file_size", 0)),
            pickle_protocol=int(settings.get("disk_pickle_protocol", 0)),
        )

    def get(self, key, default=None):
        database_key, raw = self._disk.put(key)
        row = self._connection.execute(
            "SELECT mode, filename, value FROM Cache "
            "WHERE key = ? AND raw = ? "
            "AND (expire_time IS NULL OR expire_time > ?)",
            (database_key, raw, time.time()),
        ).fetchone()
        if row is None:
            return default
        mode, filename, value = row
        try:
            return self._disk.fetch(mode, filename, value, read=False)
        except OSError:
            return default

    def __getitem__(self, key):
        value = self.get(key, ENOVAL)
        if value is ENOVAL:
            raise KeyError(key)
        return value

    def __contains__(self, key):
        return self.get(key, ENOVAL) is not ENOVAL

    def __len__(self):
        row = self._connection.execute("SELECT COUNT(*) FROM Cache").fetchone()
        return int(row[0])

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def open_cache(directory, read_only: bool = False):
    return ImmutableDiskCache(directory) if read_only else Cache(str(directory))
