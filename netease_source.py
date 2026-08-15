"""
网易云音乐歌词来源模块。

负责检测当前播放歌曲、获取歌词数据，
并通过信号向其他模块提供歌词更新事件。
"""

import re
import time
import threading

import requests

from PySide6.QtCore import QObject, QTimer, Signal

from config import (
    MAX_DELAY_COMPENSATION,
    LYRIC_MANUAL_OFFSET,
    NETEASE_POLL_INTERVAL
)

from lrc_parser import parse_lrc_text


class NetEaseBridge(QObject):
    """
    网易云歌词请求结果的信号桥接。

    用于后台请求完成后向主线程发送结果。
    """

    result = Signal(str, str, str, str)


class NetEaseMusic:
    """
    网易云音乐数据接口。

    负责歌词搜索以及歌词获取。
    """

    PROCESS_NAME = "cloudmusic.exe"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
    }

    @staticmethod
    def get_all_player_pids():
        """
        获取当前运行中的网易云音乐进程 PID。

        Returns:
            网易云音乐进程 PID 列表。
            未找到进程时返回空列表。
        """

        try:
            import psutil
        except ImportError:
            print("[网易云] 缺少 psutil，请执行：pip install psutil")
            return []

        result = []

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info["name"]

                if (
                    name
                    and
                    name.lower() == NetEaseMusic.PROCESS_NAME.lower()
                ):
                    result.append(proc.info["pid"])

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess
            ):
                continue

        print(f"[网易云] 检测到进程 PID: {result}")
        return result

    @staticmethod
    def get_song_from_all_windows():
        """
        从网易云窗口标题中解析当前歌曲信息。

        扫描所有网易云窗口，并解析
        “歌曲名 - 歌手”的标题格式。
        """

        try:
            import win32gui
            import win32process

        except ImportError:
            print("[网易云] 缺少 pywin32，请执行：pip install pywin32")
            return None, None

        # 匹配窗口标题格式：歌曲名 - 歌手
        pattern = re.compile(
            r"^(.+?)\s*-\s*(.+?)$"
        )

        pids = set(
            NetEaseMusic.get_all_player_pids()
        )

        candidates = []

        # 遍历所有窗口，查找网易云音乐窗口标题
        def callback(hwnd, _):

            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return

                _, pid = win32process.GetWindowThreadProcessId(hwnd)

                if pid not in pids:
                    return

                title = win32gui.GetWindowText(hwnd).strip()

                if title:
                    print(
                        f"[网易云] PID={pid} 窗口标题: {title}"
                    )
                    candidates.append(title)

            except Exception:
                pass

        try:
            win32gui.EnumWindows(callback, None)

        except Exception as exc:
            print(f"[网易云] 枚举窗口失败: {exc}")
            return None, None

        for title in candidates:

            match = pattern.match(title)

            if not match:
                continue

            song = match.group(1).strip()
            artist = match.group(2).strip()

            if song.lower() in (
                "netease cloud music",
                "网易云音乐"
            ):
                continue

            print(
                f"[网易云] 识别成功: {song} - {artist}"
            )

            return song, artist

        print("[网易云] 未找到歌曲标题窗口")
        return None, None

    @staticmethod
    def get_current_song():

        return NetEaseMusic.get_song_from_all_windows()

    @staticmethod
    def fetch_lyrics(song, artist=""):
        """
        根据歌曲信息获取 LRC 歌词。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。

        Returns:
            LRC 歌词文本，获取失败返回 None。
        """

        keyword = f"{song} {artist}".strip()

        try:
            # 搜索歌曲
            search_url = "https://music.163.com/api/search/get"

            response = requests.get(
                search_url,
                params={
                    "s": keyword,
                    "type": 1,
                    "limit": 1,
                },
                headers=NetEaseMusic.HEADERS,
                timeout=5
            )

            response.raise_for_status()

            data = response.json()

            songs = (
                data
                .get("result", {})
                .get("songs", [])
            )

            if not songs:

                print(
                    f"[网易云] 搜索不到：{keyword}"
                )

                return None

            song_id = songs[0].get("id")

            if not song_id:
                return None

            print(
                f"[网易云] song_id={song_id}"
            )

            # 获取歌词
            lyric_url = "https://music.163.com/api/song/lyric"

            lyric_response = requests.get(
                lyric_url,
                params={
                    "id": song_id,
                    "lv": 1,
                    "kv": 1,
                    "tv": -1,
                },
                headers=NetEaseMusic.HEADERS,
                timeout=5
            )

            lyric_response.raise_for_status()

            lyric_data = lyric_response.json()

            lrc = (
                lyric_data
                .get("lrc", {})
                .get("lyric", "")
            )

            if not lrc or "[" not in lrc:

                print(
                    f"[网易云] 「{song}」没有可用 LRC"
                )

                return None

            return lrc

        except requests.RequestException as exc:

            print(
                f"[网易云] 网络请求失败：{exc}"
            )

        except Exception as exc:

            print(
                f"[网易云] 获取歌词失败：{exc}"
            )

        return None


class NeteaseSource(QObject):
    """
    网易云歌词来源管理器。

    负责轮询歌曲状态、获取歌词以及发送歌词事件。
    """

    # 参数：
    # lyrics: 解析后的歌词列表
    # start_offset: 歌词显示起始偏移时间
    # song, artist: 当前歌曲信息
    lyrics_ready = Signal(list, float, str, str)

    # 当前歌曲发生变化时，立即通知界面清除上一首歌词
    lyrics_cleared = Signal()

    def __init__(self, poll_interval=NETEASE_POLL_INTERVAL, parent=None):
        """
        初始化歌词来源服务。

        创建轮询定时器，并准备歌词请求状态。
        """

        super().__init__(parent)

        self.bridge = NetEaseBridge()

        self.bridge.result.connect(
            self._on_fetch_done
        )

        self.poll_timer = QTimer(self)

        self.poll_timer.timeout.connect(
            self.poll
        )

        self.poll_timer.start(poll_interval)

        self.fetching = False
        self.current_song_key = None

        # 「识别到新歌曲开始播放」那一刻的墙钟时间，
        # 用来在歌词准备好后计算需要补偿多少延迟。
        self.song_detect_time = None

    def poll(self):
        """
        检查当前播放歌曲是否发生变化。

        检测到新歌曲后异步获取歌词。
        """

        if self.fetching:
            return

        song, artist = NetEaseMusic.get_current_song()

        if not song:
            return

        song_key = (
            song.strip().lower(),
            artist.strip().lower()
        )

        if song_key == self.current_song_key:
            return

        self.current_song_key = song_key

        # 歌曲发生变化
        #
        # 立即清除上一首歌词，避免新歌词获取期间
        # 屏幕继续显示上一首歌曲的字幕。

        self.lyrics_cleared.emit()

        print(
            f"[网易云] 检测到新歌曲：{song} - {artist}"
        )

        self.song_detect_time = time.monotonic()

        self.fetching = True

        # 在线程中执行歌词请求，避免阻塞 Qt 主线程
        def worker():

            lrc = NetEaseMusic.fetch_lyrics(
                song,
                artist
            )

            self.bridge.result.emit(
                song,
                artist,
                lrc or "",
                "ok" if lrc else "error"
            )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _on_fetch_done(
        self,
        song,
        artist,
        lrc_text,
        status
    ):
        """
        处理后台歌词请求结果。

        根据请求状态解析歌词，
        并通过信号发送给显示层。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            lrc_text: LRC 歌词文本。
            status: 请求结果状态。
        """

        self.fetching = False

        # 防止歌词请求期间发生切歌
        #
        # 歌词请求是在后台线程中进行的。
        # 如果请求期间已经切换歌曲，
        # 当前请求返回的歌词就不再属于正在播放的歌曲。

        current_song, current_artist = (
            NetEaseMusic.get_current_song()
        )

        current_song_key = (
            current_song.strip().lower(),
            current_artist.strip().lower()
        ) if current_song else None

        result_song_key = (
            song.strip().lower(),
            artist.strip().lower()
        )

        if current_song_key != result_song_key:
            print(
                f"[网易云] 歌词返回时歌曲已变化："
                f"{song} - {artist}"
                f" → "
                f"{current_song} - {current_artist}"
            )

            # 当前歌曲已经变化。
            # 不显示旧歌曲歌词，下一轮 poll 会重新获取新歌歌词。
            self.current_song_key = None

            return

        if status != "ok":

            print(
                f"[网易云] 获取歌词失败：{song} - {artist}"
            )

            return

        lyrics = parse_lrc_text(lrc_text)

        if not lyrics:

            print(
                f"[网易云] LRC 解析失败：{song} - {artist}"
            )

            return

        # 延迟补偿：
        # 计算歌词加载期间歌曲已经播放的时间，
        # 作为歌词时间轴起始偏移。

        if self.song_detect_time is not None:

            delay = (
                time.monotonic()
                - self.song_detect_time
            )

        else:

            delay = 0.0

        delay = max(
            0.0,
            min(
                delay,
                MAX_DELAY_COMPENSATION
            )
        )

        # 手动延迟补偿
        # 自动补偿负责弥补歌词读取过程产生的延迟，
        # 手动补偿则用于用户根据实际听感进行微调。
        #
        # 正数：歌词提前
        # 负数：歌词延后

        start_offset = (
                delay
                + LYRIC_MANUAL_OFFSET
        )

        print(
            f"[网易云] 已获取歌词：{song} - {artist}"
        )

        print(
            f"[网易云] 共 {len(lyrics)} 句"
            f" | 补偿延迟 {start_offset:.2f}s"
        )

        self.lyrics_ready.emit(
            lyrics,
            start_offset,
            song,
            artist
        )
