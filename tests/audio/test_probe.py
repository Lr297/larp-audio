from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Sequence

import pytest

from larp_audio_mvp.audio.probe import FfprobeAdapter
from larp_audio_mvp.audio.process import CommandResult
from larp_audio_mvp.config import AudioSettings
from larp_audio_mvp.core.errors import AudioProbeError
from larp_audio_mvp.core.errors import ProcessExecutionError


class StubRunner:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout
        self.calls: list[tuple[list[str], float]] = []

    def run(
        self, arguments: Sequence[str], *, timeout_seconds: float
    ) -> CommandResult:
        self.calls.append((list(arguments), timeout_seconds))
        return CommandResult(self.stdout, "", 0, 0.01)


class FailingRunner:
    def run(
        self, arguments: Sequence[str], *, timeout_seconds: float
    ) -> CommandResult:
        raise ProcessExecutionError("ffprobe failed")


def _adapter(runner: StubRunner | None = None) -> FfprobeAdapter:
    return FfprobeAdapter(
        runner=runner or StubRunner(),
        ffprobe_path=Path("/tools/ffprobe"),
        settings=AudioSettings(),
    )


def _stream(
    *, index: int = 0, default: int = 0, sample_rate: str = "48000"
) -> dict[str, object]:
    return {
        "index": index,
        "codec_type": "audio",
        "codec_name": "pcm_s16le",
        "sample_fmt": "s16",
        "sample_rate": sample_rate,
        "channels": 1,
        "bits_per_sample": 16,
        "time_base": "1/48000",
        "duration_ts": 96000,
        "disposition": {"default": default},
    }


def _payload(streams: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "streams": streams,
            "format": {
                "format_name": "wav",
                "format_long_name": "WAV / WAVE",
                "duration": "2.000000",
            },
        }
    )


def test_parses_exact_stream_duration_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"audio-bytes")

    info = _adapter().parse(source, _payload([_stream()]))

    assert info.codec_name == "pcm_s16le"
    assert info.sample_rate == 48_000
    assert info.channels == 1
    assert info.duration_seconds == Fraction(2, 1)
    assert info.duration_source == "stream_duration_ts"
    assert info.total_samples == 96_000
    assert info.bit_depth == 16
    assert info.file_size_bytes == len(b"audio-bytes")
    assert info.stream_index == 0
    assert info.is_canonical is True
    assert len(info.sha256 or "") == 64


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")

    with pytest.raises(AudioProbeError) as captured:
        _adapter().parse(source, "{not-json")

    assert captured.value.code == "MALFORMED_FFPROBE_JSON"


@pytest.mark.parametrize("streams", [[], [{"codec_type": "video", "index": 0}]])
def test_missing_audio_stream_is_rejected(
    tmp_path: Path, streams: list[dict[str, object]]
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"x")

    with pytest.raises(AudioProbeError) as captured:
        _adapter().parse(source, _payload(streams))

    assert captured.value.code == "NO_AUDIO_STREAM"


def test_first_default_audio_stream_is_selected(tmp_path: Path) -> None:
    source = tmp_path / "multi.mkv"
    source.write_bytes(b"x")
    first = _stream(index=1, default=0)
    second = _stream(index=4, default=1)

    info = _adapter().parse(source, _payload([first, second]))

    assert info.stream_index == 4
    assert info.warnings == ("multiple_audio_streams:selected_stream_index=4",)


def test_first_audio_stream_is_fallback_when_no_default(tmp_path: Path) -> None:
    source = tmp_path / "multi.mkv"
    source.write_bytes(b"x")

    info = _adapter().parse(
        source,
        _payload([_stream(index=3), _stream(index=7)]),
    )

    assert info.stream_index == 3


def test_missing_sample_rate_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")
    stream = _stream()
    stream.pop("sample_rate")

    with pytest.raises(AudioProbeError) as captured:
        _adapter().parse(source, _payload([stream]))

    assert captured.value.code == "MISSING_SAMPLE_RATE"


def test_missing_duration_is_preserved_as_unknown(tmp_path: Path) -> None:
    source = tmp_path / "audio.raw"
    source.write_bytes(b"x")
    stream = _stream()
    stream.pop("duration_ts")
    stream.pop("time_base")
    payload = json.dumps({"streams": [stream], "format": {"format_name": "wav"}})

    info = _adapter().parse(source, payload)

    assert info.duration_seconds is None
    assert info.total_samples is None
    assert "duration_unavailable" in info.warnings


def test_invalid_numeric_value_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")

    with pytest.raises(AudioProbeError) as captured:
        _adapter().parse(source, _payload([_stream(sample_rate="forty-eight")]))

    assert captured.value.code == "INVALID_NUMERIC_VALUE"


def test_fractional_integer_field_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")
    stream = _stream()
    stream["channels"] = 1.5

    with pytest.raises(AudioProbeError) as captured:
        _adapter().parse(source, _payload([stream]))

    assert captured.value.code == "INVALID_NUMERIC_VALUE"


def test_probe_passes_unicode_path_as_one_argument(tmp_path: Path) -> None:
    source = tmp_path / "папка с пробелами" / "голос ü.wav"
    source.parent.mkdir()
    source.write_bytes(b"x")
    runner = StubRunner(_payload([_stream()]))

    info = _adapter(runner).probe(source)

    arguments, timeout = runner.calls[0]
    assert arguments[-1] == str(source.resolve())
    assert timeout == 60.0
    assert info.source_path == source.resolve()


def test_probe_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(AudioProbeError) as captured:
        _adapter().probe(tmp_path)

    assert captured.value.code == "INPUT_NOT_FILE"


def test_probe_propagates_process_failure(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    source.write_bytes(b"x")
    adapter = FfprobeAdapter(
        runner=FailingRunner(),
        ffprobe_path=Path("/tools/ffprobe"),
        settings=AudioSettings(),
    )

    with pytest.raises(ProcessExecutionError):
        adapter.probe(source)
