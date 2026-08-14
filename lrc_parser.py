import os
import re

from models import LRCLine

# ============================================================
# 从网易云返回的 LRC 字符串解析歌词
# ============================================================

def parse_lrc_text(lrc_text):

    if not lrc_text:
        return []

    result = []

    # 一行可以有多个时间标签：
    # [00:12.34][00:15.67]歌词
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
