"""内部模块：elog 文件轮询监听。"""

import os
import time
import threading
from typing import Callable, Optional

from ._elog_analysis import decode_elog


class _ElogListener:
    def __init__(self, file_path: str, poll_interval: float = 0.3):
        self.file_path = file_path
        self.poll_interval = poll_interval
        self._file_size: int = 0
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: list[Callable[[str], None]] = []

    def on_line(self, callback: Callable[[str], None]) -> None:
        self._callbacks.append(callback)

    def _emit(self, line: str) -> None:
        line = line.strip()
        if line:
            for cb in self._callbacks:
                cb(line)

    def start(self) -> list[str]:
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(
                f"elog 文件不存在: {self.file_path}\n"
                f"请确认网易云音乐客户端 (3.0+) 已安装并至少运行过一次。"
            )
        with open(self.file_path, "rb") as f:
            buffer = f.read()
        lines = decode_elog(buffer).split("\n")
        self._file_size = len(buffer)
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        return lines

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2 * self.poll_interval)

    def _poll_loop(self) -> None:
        while self._running:
            try:
                size = os.path.getsize(self.file_path)
            except OSError:
                time.sleep(self.poll_interval)
                continue
            if size < self._file_size:
                self._file_size = 0
                time.sleep(self.poll_interval)
                continue
            if size > self._file_size:
                try:
                    with open(self.file_path, "rb") as f:
                        f.seek(self._file_size)
                        chunk = f.read()
                except (OSError, IOError):
                    time.sleep(self.poll_interval)
                    continue
                if chunk:
                    for line in decode_elog(chunk).split("\n"):
                        self._emit(line)
                    self._file_size = size
            time.sleep(self.poll_interval)
