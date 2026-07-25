from pathlib import Path

from larp_audio_mvp.gui.platform_paths import qt_application_paths


def test_qt_platform_paths_have_separate_data_and_documents_roots(qapp) -> None:
    paths = qt_application_paths()
    assert paths.results_directory.name == "LARP Audio Results"
    assert paths.data_directory.name == "LARP Audio"
    assert paths.data_directory != paths.results_directory
