"""
网易云音乐歌词来源模块。

负责根据当前歌曲获取歌词数据，
并通过信号向其他模块提供歌词更新事件。

当前歌曲信息由 CloudMusicWatcher 提供，
本模块不再通过窗口标题识别歌曲。
"""

import threading
from pathlib import Path

import requests

from PySide6.QtCore import QObject, Signal

import config
from core.lrc_parser import parse_lrc_text
from core.logger import get_logger
from core.settings_store import settings_path

logger = get_logger()


class NetEaseBridge(QObject):
    """
    网易云歌词请求结果的信号桥接。

    用于后台请求完成后向主线程发送结果。
    """

    result = Signal(str, str, str, str)


class NetEaseMusic:
    """
    网易云音乐数据接口。

    负责根据歌曲名与歌手搜索并获取 LRC 歌词。
    """

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
    def fetch_lyrics(song, artist=""):
        """
        根据歌曲信息获取 LRC 歌词。

        Args:
            song: 歌曲名称。
            artist: 歌手名称（可选）。

        Returns:
            str | None: LRC 歌词文本，获取失败返回 None。
        """

        keyword = f"{song} {artist}".strip()

        try:
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
                logger.error(f"搜索不到：{keyword}")

                return None

            song_id = songs[0].get("id")

            if not song_id:
                return None
            logger.info(f"song_id={song_id}")

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

                logger.info(f"「{song}」没有可用 LRC")

                return None

            return lrc

        except requests.RequestException as exc:

            logger.error(f"网络请求失败：{exc}")

        except Exception as exc:

            logger.error(f"获取歌词失败：{exc}")

        return None

    @staticmethod
    def fetch_lyrics_by_id(track_id):
        """直接通过歌曲 ID 获取 LRC 歌词。

        Args:
            track_id: 歌曲 ID（字符串或整数）。

        Returns:
            str | None: LRC 歌词文本，获取失败返回 None。
        """
        try:
            lyric_url = "https://music.163.com/api/song/lyric"
            response = requests.get(
                lyric_url,
                params={"id": track_id, "lv": 1, "kv": 1, "tv": -1},
                headers=NetEaseMusic.HEADERS,
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            lrc = data.get("lrc", {}).get("lyric", "")
            if lrc and "[" in lrc:
                return lrc
            else:
                logger.info(f"ID {track_id} 没有可用 LRC")
                return None
        except Exception as e:
            logger.error(f"通过 ID 获取歌词失败: {e}")
            return None


class NeteaseSource(QObject):
    """
    网易云歌词来源管理器。

    接收外部提供的当前歌曲信息，获取歌词并发送歌词事件。
    """

    # 参数：
    # lyrics: 解析后的歌词列表
    # start_offset: 歌词显示起始偏移时间
    # song, artist: 当前歌曲信息
    lyrics_ready = Signal(list, float, str, str)

    # 当前歌曲发生变化时，立即通知界面清除上一首歌词
    lyrics_cleared = Signal()

    # 歌词获取失败返回失败通知
    lyrics_failed = Signal(str, str)

    def __init__(self, parent=None):
        """
        初始化歌词来源服务。

        Args:
            parent: 可选的 Qt 父对象。
        """

        super().__init__(parent)

        self.bridge = NetEaseBridge()

        self.bridge.result.connect(
            self._on_fetch_done
        )

        self.fetching = False
        self.current_song_key = None

        self._current_track_id = None

        # 发起歌词请求时的歌曲进度（秒）。
        # 请求完成后作为歌词时间轴起点，
        # 使中途打开程序或拖动进度条后仍能对齐。
        self.song_position_at_detect = 0.0

        # 当前歌曲名与歌手，用于校验异步请求返回时是否已经切歌。
        self._pending_song = None
        self._pending_artist = None

        # 由外部注入的进度读取函数：() -> float
        self._position_provider = None

        # 缓存目录
        cache_dir = settings_path().parent / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = cache_dir

    def set_position_provider(self, provider):
        """
        设置当前播放进度的读取函数。

        Args:
            provider: 无参数可调用对象，返回当前进度秒数。
        """

        self._position_provider = provider

    def _get_cached_lyrics(self, track_id: str) -> str | None:
        """从缓存读取歌词。"""
        if not track_id or track_id == "0":
            return None
        cache_file = self._cache_dir / f"{track_id}.lrc"
        if cache_file.exists():
            try:
                return cache_file.read_text(encoding='utf-8')
            except Exception:
                return None
        return None

    def _save_cached_lyrics(self, track_id: str, lrc_text: str) -> None:
        """保存歌词到缓存。"""
        if not track_id or track_id == "0" or not lrc_text:
            return
        # 确保缓存目录存在
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"{track_id}.lrc"
        try:
            cache_file.write_text(lrc_text, encoding='utf-8')
            logger.info(f"歌词缓存已保存: {track_id}")
        except Exception as e:
            logger.warning(f"保存歌词缓存失败: {e}")

    def handle_track_change(self, song, artist, track_id_str):
        """
        处理当前歌曲变化，由 CloudMusicWatcher.track_changed 触发。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            track_id_str: 歌曲 ID 字符串。
        """

        if not song:
            return

        song_key = (
            song.strip().lower(),
            (artist or "").strip().lower()
        )

        if song_key == self.current_song_key:
            return

        if self.fetching:
            # 允许新的切歌打断旧请求的结果展示，
            # 旧请求返回时会通过 song_key 校验丢弃。
            pass

        self.current_song_key = song_key
        self._current_track_id = track_id_str
        self._pending_song = song
        self._pending_artist = artist or ""

        # 歌曲发生变化时立即清除上一首歌词，
        # 避免新歌词获取期间屏幕继续显示上一首字幕。
        self.lyrics_cleared.emit()

        logger.info(f"检测到新歌曲：{song} - {artist}")

        # 记录识别到新歌时的真实播放进度。
        if self._position_provider is not None:

            try:
                self.song_position_at_detect = float(
                    self._position_provider()
                )

            except Exception:
                self.song_position_at_detect = 0.0

        else:
            self.song_position_at_detect = 0.0

        self.fetching = True

        def worker():
            lrc = None

            # 1. 先尝试从缓存读取
            if self._current_track_id and self._current_track_id != "0":
                lrc = self._get_cached_lyrics(self._current_track_id)
                if lrc:
                    logger.info(f"使用缓存歌词: {song} - {artist}")

            # 2. 缓存未命中，请求网络
            if not lrc:
                if self._current_track_id and self._current_track_id != "0":
                    lrc = NetEaseMusic.fetch_lyrics_by_id(self._current_track_id)
                if not lrc:
                    # 回退到搜索
                    lrc = NetEaseMusic.fetch_lyrics(song, artist)
                # 如果获取成功，保存缓存
                if lrc and self._current_track_id and self._current_track_id != "0":
                    self._save_cached_lyrics(self._current_track_id, lrc)

            # 3. 发送结果
            self.bridge.result.emit(
                song,
                artist or "",
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

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            lrc_text: LRC 歌词文本。
            status: 请求结果状态，'ok' 或 'error'。
        """

        self.fetching = False

        # 防止歌词请求期间发生切歌。
        #
        # 歌词请求是在后台线程中进行的。
        # 如果请求期间已经切换歌曲，
        # 当前请求返回的歌词就不再属于正在播放的歌曲。

        result_song_key = (
            song.strip().lower(),
            (artist or "").strip().lower()
        )

        if result_song_key != self.current_song_key:
            logger.info(
                f"歌词返回时歌曲已变化，丢弃："
                f"{song} - {artist}"
            )

            return

        if status != "ok":
            logger.info(f"获取歌词失败：{song} - {artist}")
            self.lyrics_failed.emit(song, artist or "")
            return

        lyrics = parse_lrc_text(lrc_text)

        if not lyrics:
            logger.info(f"LRC 解析失败：{song} - {artist}")
            self.lyrics_failed.emit(song, artist or "")
            return

        # 使用请求发起时记录的播放进度作为起点。
        # 若请求期间进度已继续前进，再读取一次最新进度，
        # 使歌词尽量贴近当前真实播放位置。
        position = self.song_position_at_detect

        if self._position_provider is not None:

            try:
                position = float(
                    self._position_provider()
                )

            except Exception:
                pass

        # 手动延迟补偿：
        # 正数：歌词提前
        # 负数：歌词延后
        start_offset = (
                max(0.0, position)
                + config.LYRIC_MANUAL_OFFSET
        )

        logger.info(f"已获取歌词：{song} - {artist}")

        logger.info(
            f"共 {len(lyrics)} 句"
            f" | 起始进度 {start_offset:.2f}s"
        )

        self.lyrics_ready.emit(
            lyrics,
            start_offset,
            song,
            artist
        )