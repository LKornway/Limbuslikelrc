# Limbuslikelrc

受 **Limbus Company** 风格启发的网易云音乐桌面歌词悬浮窗。

自动识别当前播放歌曲与进度 → 获取 LRC 歌词 → 以逐字出现、抖动、描边、随机倾斜的方式显示在全屏透明悬浮层上。

## 功能

- 通过网易云本地日志识别当前歌曲、歌手（无需额外插件）
- 监听播放 / 暂停状态
- 同步真实播放进度（支持中途启动、拖动进度条）
- 自动获取并解析 LRC 歌词
- 逐字出现、抖动、描边、随机倾斜
- 过滤「作词 / 作曲」等非歌词元信息
- 手动时间偏移（`config.py`）

## 系统要求

- **仅支持 Windows**
- 已安装并运行 [网易云音乐](https://music.163.com/) 桌面客户端（建议 3.x 及以上）
- Python 3.9+
- 客户端至少运行过一次，以生成本地 `cloudmusic.elog`

## 安装

```bash
git clone https://github.com/LKornway/Limbuslikelrc.git
cd Limbuslikelrc
pip install -r requirements.txt
```

## 运行

```Bash
python main.py
```

按 Esc 退出。

## 配置

主要显示与时间参数可在根目录 config.py 中调整，例如：

- 字体、颜色、抖动强度、倾斜角度
- 逐字出现间隔
- 歌词生命周期与重叠时间
- 手动时间偏移 LYRIC_MANUAL_OFFSET（正数提前，负数延后）

## 项目结构

```text
Limbuslikelrc/
├── main.py                 # 程序入口
├── config.py               # 显示、动画与时间偏移参数
├── requirements.txt        # Python 依赖
├── Limbuslikelrc.spec      # 打包配置
├── core/                   # 数据与播放状态
│   ├── __init__.py
│   ├── cloudmusic_watcher.py   # 本地 elog 监听（歌曲 / 播放暂停 / 进度）
│   ├── netease_source.py       # 歌词请求与下发
│   ├── lrc_parser.py           # LRC 解析与元信息过滤
│   └── models.py               # 歌词与字符状态数据模型
└── ui/                     # 界面与渲染
    ├── __init__.py
    └── overlay.py              # 全屏悬浮窗与逐字动画
```

## 工作原理（简要）

1. core/cloudmusic_watcher.py 通过 netease-cloudmusic-detector 读取网易云本地
   %LOCALAPPDATA%\NetEase\CloudMusic\cloudmusic.elog，获取当前歌曲、播放状态与进度。
2. core/netease_source.py 在切歌后请求 LRC，并由 core/lrc_parser.py 解析。
3. ui/overlay.py 按时间轴渲染逐字动画；拖动进度条时仅恢复当前仍应可见的歌词，避免历史句子一次铺满。

## 已知限制

- 目前仅支持 Windows。
- 目前仅支持网易云音乐桌面客户端。
- 播放状态依赖本地 cloudmusic.elog。
- 歌词内容依赖网易云相关网络接口。
- 若 elog 不存在或客户端版本差异较大，可能无法正确识别进度。

## 许可证

本项目采用 MIT License。