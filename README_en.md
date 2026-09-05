# Limbuslikelrc

A desktop floating lyrics overlay inspired by the style of Limbus Company, supporting NetEase Cloud Music, QQ Music, and Kugou Music.

Automatically detect the currently playing song and progress → fetch lyrics → display them on a full-screen transparent overlay with per-character reveal, jitter, outline, and random tilt animations.

## Preview

<img src="assets/effect.png" alt="Lyrics effect" width="400">
<img src="assets/Interface_effect.png" alt="Main window" width="400">
<img src="assets/Setting_effect.png" alt="Settings" width="150">

## Features

- **Multi-platform support**: After choosing the "music platform" in settings and restarting, the corresponding monitor recognizes the current playback
  - NetEase Cloud Music: local log `cloudmusic.elog` (compatible with desktop and Microsoft Store editions)
  - QQ Music: Windows System Media Transport Controls (SMTC), real-time progress and cover
  - Kugou Music: window title + local lyric cache (`.krc`), album art taken from local cache
- **Real-time listening for play/pause and progress** (NetEase / QQ), supports mid-play startup and seeking
- Automatically fetch and parse lyrics: LRC and Kugou KRC (including per-character timing), filters meta-information like "lyrics/composer/Lyrics by" and leading title lines like "Song - Artist"
- **Lyrics caching**: lyrics played before are automatically cached locally and can be displayed offline (Kugou directly reuses its local KRC cache)
- Full-screen per-character reveal, jitter, outline, and random tilt animation
- **Automatic theme colors**: extract primary and contrast colors from album art and apply them to lyric text and outline
- **Main window**: shows cover art, song title, artist, progress bar, and total duration; supports dragging and resizing
- **Playback controls**: built-in Previous / Play-Pause / Next buttons in the main window, dispatched per platform (NetEase hotkeys / QQ & Kugou via SMTC)
- **One-click hide lyrics**: a button in the bottom-right of the main window toggles the overlay; hiding stops animations to save resources
- **Custom global hotkeys**: supports custom global shortcuts (play/pause, skip, volume), effective only for NetEase Cloud Music
- **System tray**: runs in background, double-click to show main window; supports exporting logs to Desktop
- **Settings dialog**: visual adjustments for font, color, animation parameters, music platform, hotkeys, close behavior, etc.; settings auto-save
- **Auto-update check**: checks GitHub for new versions at startup and supports one-click download & install
- Manual time offset (`LYRIC_MANUAL_OFFSET`)

## System Requirements

- **Windows only**
- Python 3.9+
- Install and run the corresponding music client for the selected platform:
  - NetEase Cloud Music: desktop client or Microsoft Store edition (recommended 3.x+), must have been run at least once to generate `%LOCALAPPDATA%\NetEase\CloudMusic\cloudmusic.elog`
  - QQ Music: Windows desktop client (communicates via SMTC, no extra files required)
  - Kugou Music: desktop client (lyric cache directory auto-detected from `KuGou.ini` `LyricPath`, or common default paths)

## Installation

```bash
git clone https://github.com/LKornway/Limbuslikelrc.git
cd Limbuslikelrc
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

- Press Esc to exit the full-screen lyrics overlay (this will also exit the program)
- The main window is draggable and resizable; closing it will minimize to the tray by default (asked on first run)
- Switching the music platform requires restarting the program to take effect

## Configuration

- Visual settings: click the "Settings" button at the bottom-right of the main window to adjust **music platform**, lyric appearance, animation parameters, close behavior, etc.; all changes take effect immediately and persist.
- Hotkey customization: in the settings dialog click the hotkey input box and press the new combination to record it (must include at least one modifier: Ctrl/Alt/Shift). Hotkeys apply only to NetEase Cloud Music.
- Manual config file: `config.py` provides default values; settings modified via the UI will override these and are saved to `%APPDATA%\Limbuslikelrc\settings.json`.
- Common parameters:
  - `LYRIC_MANUAL_OFFSET`: manual time offset (positive moves lyrics earlier, negative delays them)
  - Font, color, jitter strength, tilt angle, per-character reveal interval, etc.

## Project Structure

```
Limbuslikelrc/
├── main.py                 # Program entrypoint (assembles monitors and lyric sources per platform)
├── config.py               # Default configuration (overridden by user settings)
├── requirements.txt        # Python dependencies
├── Limbuslikelrc.spec      # Packaging config (optional)
├── assets/                 # Icons and preview images
│   └── app.ico             # Application icon (multi-size)
├── libs/                   # Local third-party libraries
│   └── cloudmusic_detector/   # Modified NetEase status watcher (supports desktop & Store versions)
├── core/                   # Core modules
│   ├── Cloudmusic/             # NetEase monitoring
│   │   ├── cloudmusic_watcher.py    # local elog watcher (song/play/pause/progress)
│   │   ├── netease_source.py        # lyric fetching & dispatch (with caching)
│   │   └── cloudmusic_controller.py # playback control (simulate global hotkeys)
│   ├── QQmusic/               # QQ Music monitoring
│   │   ├── qqmusic_watcher.py      # SMTC listener (song/progress/cover/control)
│   │   └── qqmusic_source.py        # resolve songmid → lyrics (by album disambiguation)
│   ├── Kugou/                 # Kugou monitoring
│   │   ├── kugou_paths.py          # lyric dir / main window detection (tolerant across versions)
│   │   ├── krc_utils.py            # KRC decryption & parsing (including per-character timing)
│   │   ├── kugou_watcher.py        # window-title based song detection + local clock progress
│   │   └── kugou_source.py          # local KRC / online lyrics + local cover art
│   ├── lrc_parser.py           # LRC/KRC line parsing & meta filtering
│   ├── models.py               # lyric & character-state data models
│   ├── settings_store.py       # user settings persistence (read/write JSON)
│   ├── logger.py               # logging (rotation & export)
│   ├── color_analyzer.py       # album art color extraction (auto theme)
│   └── updater.py              # auto-update detection & install
└── ui/                     # UI modules
    ├── __init__.py
    ├── main_window.py          # main window (cover, progress, controls, tray)
    ├── overlay.py              # full-screen lyrics overlay & per-character animation
    └── settings_dialog.py      # settings dialog (hotkey customization, cache clearing)
```

## How Each Platform Works

| Platform | Song / Track Change Detection | Playback Progress | Lyrics | Cover Art |
|---|---:|---:|---|---|
| NetEase Cloud Music | Parse local `cloudmusic.elog` (auto-detect desktop/Store paths) | Realtime progress from log (supports seeking / mid-play start) | NetEase LRC API + local cache | NetEase cover art flow |
| QQ Music | SMTC session (title/artist/album; album used for same-name disambiguation) | Realtime progress via SMTC | `lyric_new` API + local cache (keyed by songmid) | SMTC cover art stream |
| Kugou Music | Main window title "Artist - Song - Kugou Music" (works with various window sizes) | Local clock accumulation from song-change time (see limitations) | Local `.krc` decryption / online lyric API (hash key) | Local cover art cache |

## Known Limitations

- Windows only.
- **NetEase**: depends on local `cloudmusic.elog`; if the client hasn't been run or the version differs significantly, detection may fail.
- **QQ Music**: SMTC doesn't provide a global song ID; disambiguation uses album name and may mismatch when album metadata is missing.
- **Kugou Music**:
  - The client does not provide playback progress, and the UI progress is not reliably detectable; progress is accumulated from the local clock starting at song-change time and cannot detect pause/resume, causing drift over long play sessions.
  - Cannot display total song duration (progress bar shows `--:--`).
  - Cannot run in tray for stable progress detection (this program does not require Kugou to run in tray, but detection relies on title polling).
- Online lyric fetching (when not found in local caches) requires a network connection.

## License

This project is released under the MIT License.
