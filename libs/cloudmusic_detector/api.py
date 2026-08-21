import time
import asyncio
import threading
from typing import Callable, Optional

from ._elog_listener import _ElogListener
from ._elog_analysis import parse_header, get_event_type
from ._constant import CLOUDMUSIC_ELOG_PATH, ELOG_RULES, parse_args
from ._webdb import _Webdb
from .types import Track, PlayingState, PlayState


class CloudMusic:
    """
    网易云音乐播放状态监听 — 歌词软件集成接口。

    用法（同步）::

        from cloudmusic_detector import CloudMusic, Track, PlayingState

        cm = CloudMusic()
        cm.on_track_change(lambda track: print(f"切歌: {track.name}"))
        cm.on_state_change(lambda state: print(f"{'播放' if state.is_playing else '暂停'}"))
        cm.on_seek(lambda pos: print(f"跳转: {pos}s"))
        cm.start()

        # 在你的主循环中轮询
        state = cm.state   # PlayingState 快照
        track = cm.track   # 当前 Track（便捷属性）

        cm.stop()

    用法（asyncio）::

        from cloudmusic_detector import AsyncCloudMusic

        async def main():
            cm = AsyncCloudMusic()
            cm.on_track_change(lambda t: print(t.name))
            await cm.start()

            state = cm.state
            await cm.stop()
    """

    def __init__(
        self,
        *,
        elog_path: Optional[str] = None,
        webdb_path: Optional[str] = None,
        poll_interval: float = 0.3,
    ):
        """
        Args:
            elog_path:     cloudmusic.elog 路径，默认自动检测
            webdb_path:    webdb.dat 路径，默认自动检测
            poll_interval: 文件轮询间隔（秒），默认 0.3
        """
        self._listener = _ElogListener(elog_path or CLOUDMUSIC_ELOG_PATH, poll_interval)
        self._webdb = _Webdb(webdb_path)

        # 内部状态
        self._song_id: int = -1
        self._track = Track()
        self._pausing: bool = False
        self._position: float = 0.0
        self._relative_time: int = 0

        # 回调
        self._on_track_change_cbs: list[Callable[[Track], None]] = []
        self._on_state_change_cbs: list[Callable[[PlayingState], None]] = []
        self._on_seek_cbs: list[Callable[[float], None]] = []

    # ────────────────────────────────
    # 公开属性：歌词软件主要用这些
    # ────────────────────────────────

    @property
    def state(self) -> PlayingState:
        """当前播放状态快照。主循环中每次调用获取最新值。"""
        if self._song_id == -1:
            return PlayingState(state=PlayState.STOPPED)
        now = time.time() * 1000
        pos = (
            self._position
            if self._pausing
            else min((now - self._relative_time) / 1000, self._track.duration)
        )
        return PlayingState(
            state=PlayState.PAUSED if self._pausing else PlayState.PLAYING,
            track=self._track,
            position=pos,
        )

    @property
    def track(self) -> Track:
        """当前歌曲信息。"""
        return self._track

    @property
    def is_playing(self) -> bool:
        """是否正在播放。"""
        return self._song_id != -1 and not self._pausing

    @property
    def position(self) -> float:
        """当前播放位置（秒）。"""
        return self.state.position

    # ────────────────────────────────
    # 事件注册
    # ────────────────────────────────

    def on_track_change(self, callback: Callable[[Track], None]) -> None:
        """注册切歌回调，参数为新的 Track 对象。"""
        self._on_track_change_cbs.append(callback)

    def on_state_change(self, callback: Callable[[PlayingState], None]) -> None:
        """注册播放/暂停切换回调，参数为 PlayingState 快照。"""
        self._on_state_change_cbs.append(callback)

    def on_seek(self, callback: Callable[[float], None]) -> None:
        """注册进度拖拽回调，参数为新位置（秒）。"""
        self._on_seek_cbs.append(callback)

    def _emit_track(self, track: Track) -> None:
        for cb in self._on_track_change_cbs:
            try:
                cb(track)
            except Exception:
                pass

    def _emit_state(self, state: PlayingState) -> None:
        for cb in self._on_state_change_cbs:
            try:
                cb(state)
            except Exception:
                pass

    def _emit_seek(self, pos: float) -> None:
        for cb in self._on_seek_cbs:
            try:
                cb(pos)
            except Exception:
                pass

    # ────────────────────────────────
    # 启动 / 停止
    # ────────────────────────────────

    def start(self) -> None:
        """
        启动监听。启动时会回溯已有日志恢复当前状态。
        阻塞约 1~2 秒（回溯开销），之后在后台线程运行。

        Raises:
            FileNotFoundError: elog 文件不存在
        """
        lines = self._listener.start()
        self._preload(lines)
        self._listener.on_line(self._handle_line)

    def stop(self) -> None:
        """停止监听，释放资源。"""
        self._listener.stop()
        self._webdb.close()

    # ────────────────────────────────
    # 内部：状态机
    # ────────────────────────────────

    def _reset(self) -> None:
        self._song_id = -1
        self._track = Track()
        self._pausing = False
        self._position = 0.0
        self._relative_time = 0

    def _make_track(self, data: dict) -> Track:
        """从 JSON 数据构建 Track（兼容 SET_PLAYING / PLAY_ONE / webdb 三种结构）。"""
        # SET_PLAYING 结构: {id, name, artists:[{name}], album:{name, cover}, duration}
        # PLAY_ONE 结构: {track:{id, name, artists, album, duration}}
        # webdb 结构: {id, name, artists, album, duration}
        track_data = data.get("track", data)
        album = track_data.get("album", {})
        return Track(
            id=int(track_data.get("id", track_data.get("songId", -1))),
            name=track_data.get("name", ""),
            artists=tuple(a.get("name", "") for a in track_data.get("artists", [])),
            album=album.get("name", ""),
            cover_url=album.get("cover", ""),
            duration=track_data.get("duration", 0) / 1000,
        )

    def _set_new_track(self, track: Track, pausing: bool = True) -> None:
        self._song_id = track.id
        self._track = track
        self._pausing = pausing
        self._position = 0.0
        # pausing=False（PLAY_ONE 立即播放）时若 _relative_time 为 0，
        # state.position 会变成 (now-0)/1000 = Unix 秒级时间戳（历史 bug），
        # 这里把基准时间设为当前时刻，使进度从 0 正常递增。
        self._relative_time = 0 if pausing else int(time.time() * 1000)
        self._emit_track(track)

    def _preload(self, lines: list[str]) -> None:
        """启动回溯：倒序找到最近切歌事件，正序回放进度和状态。"""
        now = time.time() * 1000
        records: list[str] = []

        song_id = -1
        song_play_time = 0
        song_position = 0.0
        song_pausing = False
        song_track: Optional[Track] = None

        for line in reversed(lines):
            header = parse_header(line)
            if not header:
                continue
            records.append(line)

            etype = get_event_type(line, ELOG_RULES)
            if etype is None:
                continue

            if etype == "EXIT":
                self._reset()
                return

            if song_id != -1:
                continue

            if etype in ("SET_PLAYING", "PLAY_ONE_TRACKIN_PLAYING_LIST"):
                data = parse_args(etype, line)
                if data and isinstance(data, dict):
                    song_track = self._make_track(data)
                    song_id = song_track.id
                    song_play_time = header.timestamp
                break

            if etype == "NATIVE_SONG_LOAD":
                data = parse_args(etype, line)
                if data and isinstance(data, dict):
                    sid = int(data.get("songId", -1))
                    detail = self._webdb.wait_for_song_detail(sid, timeout=2)
                    if detail:
                        song_track = self._make_track(detail)
                        song_id = song_track.id
                        song_play_time = header.timestamp
                break

        # 正序回放进度和状态
        records.reverse()
        last_action = song_play_time
        for line in records:
            header = parse_header(line)
            if not header:
                continue
            etype = get_event_type(line, ELOG_RULES)
            if etype is None:
                continue
            if etype == "SET_PLAYING_POSITION":
                pos = parse_args("SET_PLAYING_POSITION", line)
                if pos is not None:
                    song_position = float(pos)
                    last_action = header.timestamp
            elif etype == "SET_PLAYING_STATUS":
                st = parse_args("SET_PLAYING_STATUS", line)
                if st is not None:
                    offset = header.timestamp - last_action
                    last_action = header.timestamp
                    song_pausing = (int(st) == 2)
                    if song_pausing:
                        song_position += offset / 1000

        if not song_pausing:
            song_position += (now - last_action) / 1000

        self._song_id = song_id
        self._pausing = song_pausing
        self._position = song_position if song_pausing else 0
        self._relative_time = 0 if song_pausing else int(now - song_position * 1000)
        if song_track:
            self._track = song_track

    def _handle_line(self, line: str) -> None:
        """实时处理新日志行。"""
        header = parse_header(line)
        if not header:
            return
        now = time.time() * 1000
        offset = (now - header.timestamp) / 1000
        etype = get_event_type(line, ELOG_RULES)
        if etype is None:
            return

        if etype == "EXIT":
            self._reset()
            self._emit_track(Track())
            return

        if etype == "SET_PLAYING":
            data = parse_args(etype, line)
            if not data or not isinstance(data, dict):
                return
            track = self._make_track(data)
            if track.id == self._song_id:
                return
            self._set_new_track(track, pausing=True)
            return

        if etype == "PLAY_ONE_TRACKIN_PLAYING_LIST":
            data = parse_args(etype, line)
            if not data or not isinstance(data, dict):
                return
            track = self._make_track(data)
            if track.id == self._song_id:
                return
            self._set_new_track(track, pausing=False)
            return

        if etype == "NATIVE_SONG_LOAD":
            data = parse_args(etype, line)
            if not data or not isinstance(data, dict):
                return
            new_id = int(data.get("songId", -1))
            if new_id == self._song_id:
                return
            detail = self._webdb.wait_for_song_detail(new_id, timeout=2)
            if not detail:
                return
            track = self._make_track(detail)
            new_rel = now - self._position * 1000
            new_pos = (now - self._relative_time) / 1000
            self._song_id = track.id
            self._track = track
            self._position = new_pos - offset if self._pausing else 0
            self._relative_time = 0 if self._pausing else int(new_rel - offset * 1000)
            self._emit_track(track)
            return

        if etype == "SET_PLAYING_POSITION":
            pos = parse_args(etype, line)
            if pos is None:
                return
            pos = float(pos)
            self._position = pos if self._pausing else 0
            self._relative_time = 0 if self._pausing else int(now - pos * 1000 - offset * 1000)
            self._emit_seek(self.state.position)
            return

        if etype == "SET_PLAYING_STATUS":
            st = parse_args(etype, line)
            if st is None:
                return
            new_rel = now - self._position * 1000
            new_pos = (now - self._relative_time) / 1000
            self._pausing = (int(st) == 2)
            self._position = new_pos - offset if self._pausing else 0
            self._relative_time = 0 if self._pausing else int(new_rel - offset * 1000)
            self._emit_state(self.state)


class AsyncCloudMusic(CloudMusic):
    """
    asyncio 版本。回调在事件循环中调度，适合 Tauri / Qt asyncio / 纯 async 框架。

    与同步版的关键差异：
    - ``start()`` / ``stop()`` 为真正的异步，文件读取、日志回溯等阻塞操作
      通过 ``asyncio.to_thread`` 在后台线程执行，**不会阻塞事件循环**；
    - 实时日志处理（含 webdb 查询，单次最多 2 秒）在库内部轮询线程完成，
      只把轻量的回调调度回事件循环线程；
    - 回调签名为 ``cb(track)`` / ``cb(state)`` / ``cb(position)``，均在事件循环线程触发。

    用法::

        from cloudmusic_detector import AsyncCloudMusic

        async def main():
            cm = AsyncCloudMusic()
            cm.on_track_change(lambda t: print(t.name))
            await cm.start()
            state = cm.state  # 随时读取
            await cm.stop()
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """异步启动，不阻塞事件循环（文件读取 + 日志回溯在后台线程执行）。"""
        self._loop = asyncio.get_running_loop()
        lines = await asyncio.to_thread(self._listener.start)
        await asyncio.to_thread(self._preload, lines)
        # 实时行处理注册在预载之后，且运行在库内部轮询线程，
        # 阻塞的 webdb 查询不会占用事件循环
        self._listener.on_line(self._handle_line)

    async def stop(self) -> None:
        """异步停止，不阻塞事件循环。"""
        await asyncio.to_thread(self._listener.stop)
        # check_same_thread=False 后，webdb 连接可跨线程安全关闭
        self._webdb.close()

    def _emit_track(self, track: Track) -> None:
        """切歌回调：调度到事件循环线程执行。"""
        self._marshal_callbacks(self._on_track_change_cbs, (track,))

    def _emit_state(self, state: PlayingState) -> None:
        """播放/暂停回调：调度到事件循环线程执行。"""
        self._marshal_callbacks(self._on_state_change_cbs, (state,))

    def _emit_seek(self, pos: float) -> None:
        """进度回调：调度到事件循环线程执行。"""
        self._marshal_callbacks(self._on_seek_cbs, (pos,))

    def _marshal_callbacks(self, callbacks: list, args: tuple) -> None:
        """把回调调度到事件循环线程；循环未运行则直接执行（兜底）。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._dispatch_callbacks, callbacks, args)
        else:
            self._dispatch_callbacks(callbacks, args)

    @staticmethod
    def _dispatch_callbacks(callbacks: list, args: tuple) -> None:
        for cb in callbacks:
            try:
                cb(*args)
            except Exception:
                pass
