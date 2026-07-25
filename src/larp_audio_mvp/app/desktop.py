"""Desktop application entry point."""

from __future__ import annotations

import multiprocessing
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _technical_mode(arguments: list[str]) -> int | None:
    if not arguments or arguments[0] not in {"--verify-installation", "--packaged-self-test", "--prepare-engine"}:
        return None
    if arguments[0] == "--prepare-engine":
        if len(arguments) != 2:
            raise SystemExit("--prepare-engine requires APPLICATION_DATA_DIRECTORY")
        from larp_audio_mvp.speech_engine import SpeechEngineManager

        manager = SpeechEngineManager(Path(arguments[1]))
        manager.prepare()
        status = manager.status()
        print(json.dumps({"engine_ready": status.readiness.value == "ready", "version": status.installed_version}, sort_keys=True))
        return 0
    from larp_audio_mvp.runtime import BundledResourceResolver

    resolver = BundledResourceResolver.current(developer_mode=False)
    ffmpeg, ffprobe = resolver.assert_packaged_resources()
    if arguments[0] == "--verify-installation":
        versions = {}
        for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
            completed = subprocess.run([str(path), "-version"], capture_output=True, text=True, timeout=10, env={"PATH": ""})
            if completed.returncode:
                raise SystemExit(f"Bundled {name} failed")
            versions[name] = completed.stdout.splitlines()[0]
        from larp_audio_mvp.alignment.tokenizer import tokenize_script
        from larp_audio_mvp.core.contracts import ScriptTokenKind
        from larp_audio_mvp.subtitles.syntax import LocalEnglishSyntaxAnalyzer

        probe_text = "Local syntax remains available."
        probe_words = tuple(
            token
            for token in tokenize_script(probe_text)
            if token.kind is ScriptTokenKind.WORD
        )
        syntax = LocalEnglishSyntaxAnalyzer(allow_fallback=False).analyze(
            probe_text, probe_words
        )
        print(json.dumps({
            "resources_ready": True,
            "media": versions,
            "syntax": {
                "mode": syntax.mode.value,
                "model": syntax.model_name,
                "version": syntax.model_version,
            },
        }, sort_keys=True))
        return 0
    if len(arguments) != 5:
        raise SystemExit("--packaged-self-test requires AUDIO SCRIPT MODEL_DIRECTORY OUTPUT_PARENT")
    from larp_audio_mvp.app.process_audio import main as process_main

    return process_main([
        "--audio", arguments[1], "--script-file", arguments[2],
        "--model-path", arguments[3], "--model", "small",
        "--output-parent", arguments[4], "--ffmpeg", str(ffmpeg),
        "--ffprobe", str(ffprobe), "--device", "cpu", "--compute-type", "int8",
    ])


def main(argv: Sequence[str] | None = None) -> int:
    multiprocessing.freeze_support()
    arguments = list(argv) if argv is not None else sys.argv[1:]
    technical_result = _technical_mode(arguments)
    if technical_result is not None:
        return technical_result
    from larp_audio_mvp.gui.application import run

    return run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
