from __future__ import annotations

import os
import subprocess
import sys


def test_gui_module_import_does_not_create_qapplication() -> None:
    code = (
        "from PySide6.QtWidgets import QApplication; "
        "import larp_audio_mvp.gui.application; "
        "assert QApplication.instance() is None; print('no-import-side-effect')"
    )
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "no-import-side-effect"


def test_application_factory_creates_named_application() -> None:
    code = (
        "from larp_audio_mvp.gui.application import create_application; "
        "app=create_application(['test']); "
        "print(app.applicationName(), app.organizationName())"
    )
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "LARP Audio LARP Audio"
