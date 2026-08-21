"""内部模块：elog 日志解码与解析。"""

import os
import re
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class _ElogHeader:
    pid: str
    tid: str
    timestamp: int
    log_type: str
    src: str
    lr: str
    datetime: str


_DECODE_TABLE: Optional[bytes] = None

# 系统运行时长（毫秒）与 wall-clock 的基准缓存：
# parse_header 在回溯（_preload）时会对每一行调用，而 GetTickCount64 / time.time
# 都是系统调用，在大日志（几十万行）上会显著拖慢启动。批量解析期间基准几乎不变，
# 缓存后在单个处理周期内复用，避免每行都触发系统调用。
_uptime_cache_ms: int = -1
_uptime_cache_at: float = 0.0


def _get_system_uptime_ms_cached() -> int:
    global _uptime_cache_ms, _uptime_cache_at
    now = time.time()
    # 1 秒内复用缓存
    if _uptime_cache_ms >= 0 and (now - _uptime_cache_at) < 1.0:
        return _uptime_cache_ms
    _uptime_cache_at = now
    _uptime_cache_ms = _get_system_uptime_ms()
    return _uptime_cache_ms


def _build_decode_table() -> bytes:
    """预计算逐字节解码映射表（纯函数，只依赖输入字节值）。"""
    table = bytearray(256)
    for byte in range(256):
        high = byte >> 4
        low = byte & 0x0F
        hex_digit = (high ^ ((low + 8) % 16)) % 16
        restored = hex_digit * 16 + (byte >> 6) * 4 + (~high & 3)
        table[byte] = restored & 0xFF
    return bytes(table)


def decode_elog(data: bytes) -> str:
    """解码 cloudmusic.elog 的自定义二进制编码。

    解码是逐字节的纯函数，用查表 + ``bytes.translate``（C 实现）加速，
    避免在大文件（可达 10MB+）上做逐字节 Python 循环而长时间占用 GIL。
    """
    global _DECODE_TABLE
    if _DECODE_TABLE is None:
        _DECODE_TABLE = _build_decode_table()
    buf = data.translate(_DECODE_TABLE)
    while len(buf) > 0:
        try:
            return buf.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            buf = buf[1:]
    return ""


_HEADER_RE = re.compile(
    r"^\[(\d+):(\d+):(\d{4}/\d{6}:\d+):([A-Z]+):([a-zA-Z0-9._-]+)\((\d+)\)\]\s+"
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"
)


def _get_system_uptime_ms() -> int:
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        try:
            fn = kernel32.GetTickCount64
            fn.restype = ctypes.c_uint64
            return int(fn())
        except AttributeError:
            return int(kernel32.GetTickCount())
    else:
        try:
            with open("/proc/uptime") as f:
                return int(float(f.read().split()[0]) * 1000)
        except (OSError, IOError):
            return 0


def parse_header(row: str) -> Optional[_ElogHeader]:
    m = _HEADER_RE.match(row)
    if not m:
        return None
    pid, tid, ts_str, log_type, src, lr, dt = m.groups()
    startup_time = int(ts_str.split(":")[-1])
    uptime_ms = _get_system_uptime_ms_cached()
    now_ms = int(time.time() * 1000)
    return _ElogHeader(
        pid=pid, tid=tid,
        timestamp=startup_time + (now_ms - uptime_ms),
        log_type=log_type, src=src, lr=lr, datetime=dt,
    )


def get_event_type(row: str, rules: dict) -> Optional[str]:
    for name, cfg in rules.items():
        if cfg["rule"](row):
            return name
    return None
