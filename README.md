# Limbuslikelrc

受 **Limbus Company** 风格启发的网易云音乐桌面歌词悬浮窗。

自动识别当前播放歌曲 → 获取歌词 → 以逐字出现、抖动、描边、随机倾斜的方式显示。

## 功能

- 自动识别网易云音乐当前播放歌曲
- 自动获取 LRC 歌词
- 逐字出现、抖动、描边、随机倾斜
- 跟随歌曲播放 / 暂停状态（SMTC）
- 歌词加载延迟补偿
- 手动时间偏移

## 系统要求

- **仅支持 Windows**
- 已安装并运行 [网易云音乐](https://music.163.com/)
- Python 3.9+

## 安装

```bash
git clone https://github.com/LKornway/Limbuslikelrc.git
cd Limbuslikelrc
pip install -r requirements.txt
```

## 配置

项目的主要显示参数可以在 `config.py` 中调整。

## 项目结构

```text
Limbuslikelrc/
├── main.py              # 程序入口
├── config.py            # 显示与运行参数
├── models.py            # 歌词数据模型
├── lrc_parser.py        # LRC 歌词解析
├── netease_source.py    # 网易云歌曲与歌词获取
├── smtc_watcher.py      # Windows SMTC 播放状态监听
├── overlay.py           # 歌词窗口与动画渲染
└── requirements.txt     # Python 依赖
```

## 已知限制

- 目前仅支持 Windows。
- 目前仅支持网易云音乐。
- 歌曲识别依赖网易云音乐窗口标题。
- 歌词获取依赖网易云相关接口。