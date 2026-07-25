# Clean-machine acceptance

`scripts/run_clean_machine_test.py` is a bounded host-isolation check: it uses a
temporary HOME, avoids PATH, locates packaged resources and executes bundled
FFmpeg/ffprobe. It checks independence from source `.venv` and system tools.

A real clean-Mac acceptance still requires:

1. Copy the app outside the repository and open it from Finder.
2. Use a fresh account/application-data directory.
3. Confirm Setup required, prepare the engine in the GUI, process a legal voice fixture.
4. Confirm Documents output, quit/reopen, and process again without setup.
5. Disconnect networking and confirm the prepared engine is reused.

Automated Stage 13 verification is not evidence of a separate physical clean
machine. Finder interaction, real engine setup and full processing are reported
separately and are never claimed unless executed.

Stage 13.1 additionally mounts the produced DMG, checks its app plus Applications
link, copies the app to a temporary Applications-like folder and launches that
copy with isolated application data. Lifecycle checks use a controlled local
HTTP fixture; real pinned-engine preparation and offline reuse are reported as
separate facts so simulated cancellation is never described as a real download.
