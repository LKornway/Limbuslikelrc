# -*- mode: python ; coding: utf-8 -*-

import certifi

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        # 修改版网易云监听库（含 GBK 解码修复与 Store 版兼容），
        # 运行时经 core/Cloudmusic 内的相对路径引用
        ('libs/cloudmusic_detector', 'libs/cloudmusic_detector'),
        # TLS CA 证书：requests 默认从 certifi 加载，
        # 显式收集避免 onefile 解压后找不到 cacert.pem
        (certifi.where(), 'certifi'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Limbuslikelrc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
)