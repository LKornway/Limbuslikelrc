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


# ============================================================
# 网易云音乐自动获取
#
# 参考 TempuraYMY0728/Limbus-Like-Lyric-Simulator：
# 1. 查找 cloudmusic.exe
# 2. 读取网易云主窗口标题
# 3. 从「歌名 - 歌手」中提取歌曲信息
# 4. 调用网易云搜索接口获取歌曲
# 5. 调用网易云歌词接口获取 LRC
# ============================================================

class NetEaseBridge(QObject):
    result = Signal(str, str, str, str)


class NetEaseMusic:

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
        不再寻找第一个 cloudmusic.exe。
        扫描所有网易云进程的窗口，寻找类似：
        歌名 - 歌手
        的标题。
        """

        try:
            import win32gui
            import win32process

        except ImportError:
            print("[网易云] 缺少 pywin32，请执行：pip install pywin32")
            return None, None

        pattern = re.compile(
            r"^(.+?)\s*-\s*(.+?)$"
        )

        pids = set(
            NetEaseMusic.get_all_player_pids()
        )

        candidates = []

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

        keyword = f"{song} {artist}".strip()

        try:

            # 第一步：网易云搜索
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

            # 第二步：获取歌词
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


# ============================================================
# 歌词来源服务
#
# 对外只暴露一个信号：lyrics_ready。
# 「识别新歌曲 -> 抓歌词 -> 延迟补偿」的全部细节都封装在这里，
# 使用方（LyricsOverlay）不需要知道网易云是怎么被识别出来的。
# ============================================================

class NeteaseSource(QObject):

    # lyrics: list[LRCLine]
    # start_offset: 延迟补偿后 current_time 应该从哪一秒开始
    # song, artist
    lyrics_ready = Signal(list, float, str, str)

    def __init__(self, poll_interval=NETEASE_POLL_INTERVAL, parent=None):

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

    # ========================================================
    # 轮询：识别当前播放的歌曲
    # ========================================================

    def poll(self):

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

        print(
            f"[网易云] 检测到新歌曲：{song} - {artist}"
        )

        self.song_detect_time = time.monotonic()

        self.fetching = True

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

    # ========================================================
    # 抓取结果 + 延迟补偿
    # ========================================================

    def _on_fetch_done(
        self,
        song,
        artist,
        lrc_text,
        status
    ):

        self.fetching = False

        # ----------------------------------------------------
        # 防止歌词请求期间发生切歌
        #
        # 歌词请求是在后台线程中进行的。
        # 如果请求期间网易云已经切换歌曲，
        # 当前请求返回的歌词就不再属于正在播放的歌曲。
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 延迟补偿：
        #
        # 从「识别到新歌曲开始播放」到「歌词准备好」这段时间
        # 里，歌曲已经在真实播放了。直接把这段耗时算出来，
        # 交给使用方作为播放起点。
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 手动延迟补偿
        #
        # 自动补偿负责弥补歌词读取过程产生的延迟，
        # 手动补偿则用于用户根据实际听感进行微调。
        #
        # 正数：歌词提前
        # 负数：歌词延后
        # ----------------------------------------------------

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
