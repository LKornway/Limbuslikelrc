"""
cloudmusic_detector — 网易云音乐播放状态监听库

面向桌面歌词软件的封装接口。

快速上手::

    from cloudmusic_detector import CloudMusic, Track, PlayingState, PlayState

    cm = CloudMusic()
    cm.on_track_change(lambda track: print(track.name))
    cm.start()

    state = cm.state  # PlayingState 快照
    cm.stop()

API 一览::

    cm.state           # PlayingState — 状态+进度+歌曲  (每次调用都是最新快照)
    cm.track           # Track — 当前歌曲信息
    cm.is_playing      # bool  — 是否播放中
    cm.position        # float — 当前进度(秒)

    cm.on_track_change(cb)   # 切歌回调  cb(track: Track)
    cm.on_state_change(cb)   # 暂停/播放回调  cb(state: PlayingState)
    cm.on_seek(cb)           # 进度拖拽回调  cb(position: float)

    cm.start()  /  cm.stop()

Asyncio 版本::

    from cloudmusic_detector import AsyncCloudMusic
    cm = AsyncCloudMusic()
    await cm.start()
    state = cm.state
    await cm.stop()
"""

from .types import Track, PlayingState, PlayState
from .api import CloudMusic, AsyncCloudMusic

__all__ = [
    "CloudMusic",
    "AsyncCloudMusic",
    "Track",
    "PlayingState",
    "PlayState",
]
__version__ = "2.0.3"
