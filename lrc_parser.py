"""
LRC歌词解析模块。

负责解析LRC格式歌词文本，
并转换为程序内部使用的歌词数据结构。
"""

import re

from models import LRCLine


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

    # 支持一行包含多个时间标签
    # 例：[00:12.34][00:15.67]歌词
    # 匹配 LRC 时间标签，例如：[01:23.45]
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

        for match in matches:

            minutes = int(match.group(1))
            seconds = float(match.group(2))

            timestamp = minutes * 60 + seconds

            result.append(
                LRCLine(timestamp, text)
            )

    result.sort(
        key=lambda item: item.timestamp
    )

    return result
