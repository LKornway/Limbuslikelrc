"""
LRC歌词解析模块。

负责解析LRC格式歌词文本，
并转换为程序内部使用的歌词数据结构。
"""

import re

from core.models import LRCLine

# 常见非歌词元信息行：作词/作曲/编曲等
_META_LINE_RE = re.compile(
    r"^("
    r"作词|作曲|编曲|作詞|詞|曲|编|"
    r"演唱|歌手|演唱者|原唱|翻唱|"
    r"混音|混缩|制作人|监制|出品|出品人|"
    r"录音|和声|吉他|贝斯|鼓|弦乐|"
    r"封面|插画|策划|制作|特别鸣谢|"
    r"OP|ED|歌词"
    r")\s*[:：]"
)


def _is_meta_line(text: str) -> bool:
    """
    判断是否为作词/作曲等元信息行。
    """

    return bool(_META_LINE_RE.match(text.strip()))


def parse_lrc_text(lrc_text):
    """
    解析 LRC 格式歌词文本。

    Args:
        lrc_text: LRC 格式歌词字符串。

    Returns:
        按时间排序的 LRCLine 列表。
    """

    if not lrc_text:
        return []

    result = []

    pattern = re.compile(
        r"\[(\d+):(\d+(?:\.\d+)?)\]"
    )

    for raw_line in (
        lrc_text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    ):

        raw_line = raw_line.strip()

        if not raw_line:
            continue

        matches = list(pattern.finditer(raw_line))

        if not matches:
            continue

        text = pattern.sub("", raw_line).strip()

        if not text:
            continue

        # 跳过作词/作曲等非歌词文本
        if _is_meta_line(text):
            continue

        for match in matches:

            minutes = int(match.group(1))
            seconds = float(match.group(2))
            timestamp = minutes * 60 + seconds

            result.append(
                LRCLine(timestamp, text)
            )

    result.sort(key=lambda item: item.timestamp)

    return result