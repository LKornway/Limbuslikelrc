# Limbuslikelrc

[中文](README.md) | [English](README_en.md)

受 **Limbus Company** 风格启发的桌面歌词悬浮窗，支持 **网易云音乐 / QQ 音乐 / 酷狗音乐** 三大平台。

自动识别当前播放歌曲与进度 → 获取歌词 → 以逐字出现、抖动、描边、随机倾斜的方式显示在全屏透明悬浮层上。

## 界面预览

<img src="assets/effect.png" alt="歌词效果" width="400">
<img src="assets/Interface_effect.png" alt="程序主页面" width="400">
<img src="assets/Setting_effect.png" alt="设置页面" width="150">

## 功能

- **多平台支持**：设置中选择「音乐平台」后重启生效，通过对应监测器识别当前播放
  - 网易云音乐：本地日志 `cloudmusic.elog`（桌面版 / Microsoft Store 版均兼容）
  - QQ 音乐：Windows 系统媒体控件（SMTC），实时进度与封面
  - 酷狗音乐：窗口标题 + 本地歌词缓存（`.krc`），专辑封面取自本地缓存
- **实时监听播放/暂停与进度**（网易云 / QQ），支持中途启动、拖动进度条
- 自动获取并解析歌词：LRC 与酷狗 KRC（含逐字时间轴），过滤「作词/作曲/Lyrics by」等元信息与开头「歌名 - 歌手」标题行
- **歌词缓存**：播放过的歌词自动缓存到本地，离线也可显示已缓存歌词（酷狗直接复用其本地 KRC 缓存）
- 全屏歌词逐字出现、抖动、描边、随机倾斜动画
- **自动主题色**：从专辑封面提取主色和对比色，自动应用到歌词文字和描边
- **主界面**：显示封面、歌曲名、歌手、进度条、总时长，支持拖拽缩放
- **播放控制**：主界面内置“上一首/播放暂停/下一首”按钮，按平台分发（网易云热键 / QQ·酷狗 SMTC）
- **一键隐藏歌词**：主界面右下角按钮，随时显示或隐藏歌词悬浮窗，隐藏时停止动画节省资源
- **自定义热键**：支持自定义全局快捷键（播放/暂停、切歌、音量控制），仅网易云平台生效
- **系统托盘**：后台驻留，双击显示主界面；支持一键导出日志至桌面
- **设置对话框**：可视化调节字体、颜色、动画参数、音乐平台、热键、关闭行为等，设置自动保存
- **自动更新检测**：启动后自动检测 GitHub 新版本，支持一键下载安装
- 手动时间偏移（`LYRIC_MANUAL_OFFSET`）

## 系统要求

- **仅支持 Windows**
- Python 3.9+
- 按所选平台安装并运行对应的音乐客户端：
  - 网易云音乐：桌面客户端或 Microsoft Store 版（建议 3.x 及以上），需至少运行过一次以生成本地 `%LOCALAPPDATA%\NetEase\CloudMusic\cloudmusic.elog`
  - QQ 音乐：Windows 桌面客户端（通过 SMTC 通信，无需额外文件）
  - 酷狗音乐：桌面客户端（歌词缓存目录按 `KuGou.ini` 的 `LyricPath` 自动探测，或常见默认路径）

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

- 按 Esc 退出全屏歌词悬浮窗（同时退出程序）
- 主窗口可拖拽、缩放，关闭时默认最小化到托盘（首次询问）
- 切换音乐平台后需重启程序生效

## 配置

- 可视化设置：点击主窗口右下角的「设置」按钮，可调节**音乐平台**、歌词外观、动画参数、关闭行为等，所有修改即时生效并持久化保存。
- 热键自定义：在设置页面点击热键输入框，按下新的组合键即可录入（必须包含至少一个修饰键：Ctrl/Alt/Shift）。热键仅对网易云平台生效。
- 手动配置文件：`config.py` 提供所有默认值，设置界面修改后会覆盖这些默认值，并保存到 `%APPDATA%\Limbuslikelrc\settings.json`。
- 常用参数：
  - `LYRIC_MANUAL_OFFSET`：手动时间偏移（正数提前，负数延后）
  - 字体、颜色、抖动强度、倾斜角度、逐字出现间隔等

## 项目结构

```text
Limbuslikelrc/
├── main.py                 # 程序入口（按平台装配监测器与歌词来源）
├── config.py               # 默认配置（会被用户设置覆盖）
├── requirements.txt        # Python 依赖
├── Limbuslikelrc.spec      # 打包配置（可选）
├── assets/                 # 图标与预览图
│   └── app.ico             # 应用图标（含多尺寸）
├── libs/                   # 本地第三方库
│   └── cloudmusic_detector/   # 修改版网易云状态监听库（支持桌面版和 Store 版）
├── core/                   # 核心功能模块
│   ├── Cloudmusic/             # 网易云监测
│   │   ├── cloudmusic_watcher.py    # 本地 elog 监听（歌曲/播放暂停/进度）
│   │   ├── netease_source.py        # 歌词请求与下发（含缓存）
│   │   └── cloudmusic_controller.py # 播放控制（模拟全局快捷键）
│   ├── QQmusic/               # QQ 音乐监测
│   │   ├── qqmusic_watcher.py      # SMTC 监听（歌曲/进度/封面/控制）
│   │   └── qqmusic_source.py        # 按专辑去歧义解析 songmid → 歌词
│   ├── Kugou/                 # 酷狗音乐监测
│   │   ├── kugou_paths.py          # 歌词目录/主窗口探测（多版本容错）
│   │   ├── krc_utils.py            # KRC 解密与解析（含逐字时间轴）
│   │   ├── kugou_watcher.py        # 窗口标题切歌识别 + 本地时钟进度
│   │   └── kugou_source.py          # 本地 KRC / 在线歌词 + 本地封面
│   ├── lrc_parser.py           # LRC/KRC 行解析与元信息过滤
│   ├── models.py               # 歌词与字符状态数据模型
│   ├── settings_store.py       # 用户设置持久化（读写 JSON）
│   ├── logger.py               # 日志管理（轮转与导出）
│   ├── color_analyzer.py       # 封面颜色提取（自动主题色）
│   └── updater.py              # 自动更新检测与安装
└── ui/                     # 界面模块
    ├── __init__.py
    ├── main_window.py          # 主窗口（封面、进度条、控制按钮、托盘等）
    ├── overlay.py              # 全屏歌词悬浮窗与逐字动画
    └── settings_dialog.py      # 设置对话框（含热键自定义、清除缓存）
```

## 各平台工作原理

| 平台 | 歌曲/切歌识别 | 播放进度 | 歌词 | 封面 |
|---|---|---|---|---|
| 网易云音乐 | 解析本地 `cloudmusic.elog`（桌面版/Store 版路径自动探测） | 日志实时进度（支持拖动/中途启动） | 网易云 LRC 接口 + 本地缓存 | 网易云接口 240×240 |
| QQ 音乐 | SMTC 会话（标题/歌手/专辑，专辑用于同名版本去歧义） | SMTC 实时进度 | `lyric_new` 接口 + 本地缓存（songmid 键） | SMTC 封面流 |
| 酷狗音乐 | 主窗口标题 `歌手 - 歌名 - 酷狗音乐`（兼容大小窗口） | **本地时钟累计**（见限制） | 本地 `.krc` 解密 / 在线歌词接口（hash 键） | 本地 `AlbumImg` 缓存（480/120） |

## 已知限制

- 仅支持 Windows 系统。
- **网易云**：依赖本地 `cloudmusic.elog`，客户端未运行或版本差异较大时可能无法识别。
- **QQ 音乐**：SMTC 不提供全局歌曲 ID，同名多版本依靠专辑名收敛，少数专辑缺失时可能匹配到其它版本。
- **酷狗音乐**：
  - 客户端不提供播放进度接口且界面进度不可稳定识别，进度按**本地时钟从切歌时刻累计**，无法感知暂停/继续，长时间播放会累积偏差；
  - 无法显示歌曲总时长（进度条为 `--:--`）；
  - 无法托盘运行（本程序对酷狗无此要求，但进度识别依赖歌名标题轮询）。
- 歌词在线获取（网易云 / QQ / 酷狗未命中本地缓存时）需要网络连接。

## 许可证

本项目采用 MIT License。
