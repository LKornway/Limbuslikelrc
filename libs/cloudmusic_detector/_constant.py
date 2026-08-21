"""内部模块：路径常量与事件匹配规则。"""

import os
import re
import json
from typing import Any, Optional


def _get_local_app_data() -> str:
    if os.name != "nt":
        return os.environ.get(
            "CLOUDMUSIC_DIR",
            os.path.expanduser("~/.local/share/netease-cloudmusic"),
        )
    return os.environ.get(
        "LOCALAPPDATA",
        os.path.join(os.path.expanduser("~"), "AppData", "Local"),
    )


CLOUDMUSIC_DIR = os.path.join(_get_local_app_data(), "NetEase", "CloudMusic")
CLOUDMUSIC_ELOG_PATH = os.path.join(CLOUDMUSIC_DIR, "cloudmusic.elog")
CLOUDMUSIC_WEBDB_PATH = os.path.join(CLOUDMUSIC_DIR, "Library", "webdb.dat")


_JSON_RE = re.compile(r"\{.*\}")


def _extract_json(row: str) -> Optional[dict]:
    m = _JSON_RE.search(row)
    return json.loads(m.group()) if m else None


def _extract_group(row: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, row)
    return m.group(1) if m else None


# 正则预编译
_RE_POSITION = re.compile(r"【playing】,\"setPlayingPosition\",(\d+(?:\.\d+)?)")
_RE_STATUS = re.compile(r"【playing】,\"native播放state\",(\d+),")


ELOG_RULES = {
    # 客户端退出
    "EXIT": {
        "rule": lambda r: "【app】,{\"actionId\":\"exitApp\"}" in r,
        "args": lambda r: True,
    },
    # checkPlayPrivilege 切歌
    "SET_PLAYING": {
        "rule": lambda r: "【playing】,\"checkPlayPrivilege\"," in r,
        "args": lambda r: _extract_json(r),
    },
    # 播放列表切歌
    "PLAY_ONE_TRACKIN_PLAYING_LIST": {
        "rule": lambda r: "【playing】,\"playOneTrackInPlayingList\"" in r,
        "args": lambda r: _extract_json(r),
    },
    # 原生播放资源加载完成
    "NATIVE_SONG_LOAD": {
        "rule": lambda r: "【playing】,\"native播放资源load完成，开始播放\"" in r,
        "args": lambda r: _extract_json(r),
    },
    # 进度拖拽
    "SET_PLAYING_POSITION": {
        "rule": lambda r: "【playing】,\"setPlayingPosition\"" in r,
        "args": lambda r: _extract_group(r, _RE_POSITION.pattern),
    },
    # 播放/暂停状态切换  1=播放  2=暂停
    "SET_PLAYING_STATUS": {
        "rule": lambda r: "【playing】,\"native播放state\"" in r,
        "args": lambda r: _extract_group(r, _RE_STATUS.pattern),
    },
}


def parse_args(event_type: str, row: str) -> Any:
    return ELOG_RULES[event_type]["args"](row)
