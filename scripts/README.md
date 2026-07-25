# Project scripts

Этот каталог предназначен только для воспроизводимых development/release scripts. Продуктовая логика и обработка пользовательских данных здесь размещаться не должны.

Stage 13.1.1 release utilities:

- `build_ffmpeg_macos.py` rebuilds pinned LGPL media tools with a neutral prefix;
- `build_macos_app.py` performs clean wheel-first PyInstaller packaging;
- `scan_release_privacy.py` is the release-blocking deep artifact scanner;
- `create_stage_13_1_1_archives.py` seals the delta, source snapshot and handoff.
