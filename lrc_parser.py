import os
import re

from models import LRCLine


# ============================================================
# 本地 LRC 文件解析（当前作为备用，未启用）
# ============================================================

def parse_lrc(filename):

    if not os.path.exists(filename):

        print(
            f"[错误] 找不到 LRC 文件：{filename}"
        )

        return []

    pattern = re.compile(
        r"\[(\d+):(\d+(?:\.\d+)?)\](.*)"
    )

    result = []

    with open(
        filename,
        "r",
        encoding="utf-8-sig"
    ) as file:

        for raw_line in file:

            raw_line = raw_line.strip()

            if not raw_line:
                continue

            match = pattern.match(
                raw_line
            )

            if not match:
                continue

            minutes = int(
                match.group(1)
            )

            seconds = float(
                match.group(2)
            )

            text = match.group(3).strip()

            if not text:
                continue

            timestamp = (
                minutes * 60
                + seconds
            )

            result.append(
                LRCLine(
                    timestamp,
                    text
                )
            )

    result.sort(
        key=lambda x: x.timestamp
    )

    return result


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
