"""内部模块：webdb.dat SQLite 只读查询。"""

import json
import sqlite3
import os
from typing import Optional

from ._constant import CLOUDMUSIC_WEBDB_PATH


class _Webdb:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CLOUDMUSIC_WEBDB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not os.path.exists(self.db_path):
                raise FileNotFoundError(f"webdb.dat 不存在: {self.db_path}")
            # check_same_thread=False：本地只读缓存，允许在轮询线程/事件循环线程等
            # 任意线程读取与关闭，避免跨线程访问报 ProgrammingError
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def get_song_detail(self, song_id: int) -> Optional[dict]:
        try:
            row = self._get_conn().execute(
                "SELECT playtime, jsonStr FROM historyTracks ORDER BY playtime DESC LIMIT 1"
            ).fetchone()
        except (sqlite3.Error, FileNotFoundError):
            return None
        if not row:
            return None
        try:
            detail = json.loads(row["jsonStr"])
        except (json.JSONDecodeError, TypeError):
            return None
        return detail if int(detail.get("id", -1)) == song_id else None

    def wait_for_song_detail(self, song_id: int, timeout: float = 2.0) -> Optional[dict]:
        import time
        elapsed = 0.0
        while elapsed < timeout:
            detail = self.get_song_detail(song_id)
            if detail:
                return detail
            time.sleep(0.1)
            elapsed += 0.1
        return None

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()
