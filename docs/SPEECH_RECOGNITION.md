# Local speech recognition and dual-timeline timestamps

## Scope

Stage 7 runs local Faster-Whisper on an already rendered canonical `cleaned_audio.wav`, reads the immutable `edit_map.json`, and writes `recognition.json`. The result is timing evidence for a later alignment stage. This stage does not read the original script, does not change any user text, does not align words, does not create subtitles, and does not modify audio or the edit map.

The current Stage 7 sequencing is an explicit technical-stage requirement. `PRODUCT_SPEC.md` still describes production STT before safe pause planning, while Stage 7 transcribes cleaned audio after the Stage 6 technical signal-only cut. Therefore this implementation cannot retroactively prove that a Stage 6 cut was speech-safe. The production ordering and guard policy remain a pre-alignment decision; `recognition.json` does not upgrade the Stage 6 map to a release-safe map.

## Architecture

Responsibilities are separated:

- `LocalWhisperModelManager` selects only `tiny`, `base`, or `small`, validates an explicit local directory, and fingerprints its required files;
- `FasterWhisperInference` owns the runtime import, model construction, inference options, and mapping of Faster-Whisper objects into backend-neutral observations;
- `RecognitionMapper` quantizes observed seconds to cleaned samples and uses the existing `TimelineMapper` for cleaned-to-original mapping;
- `LocalSpeechRecognizer` orchestrates those components through the existing `SpeechRecognizer` port;
- `models.serialization` creates deterministic versioned JSON and publishes it atomically;
- `app.recognize_speech` is a developer CLI, not product UI.

The adapter invokes `WhisperModel` with an absolute local directory and `local_files_only=True`. It never passes `tiny`, `base`, `small`, or another Hub identifier to the runtime. Required local files are `config.json`, `model.bin`, and `tokenizer.json`; requiring the tokenizer prevents an incomplete converted model from attempting a later tokenizer lookup.

## STT text is not canonical text

`RecognizedWord.text` preserves the backend observation exactly, including leading whitespace or punctuation attachment. It is not normalized, corrected, stripped, translated, or compared with the user script in this stage.

This field may be consumed only as evidence by a future aligner. It must never be used by a subtitle serializer, display layer, or fallback text path. The original user script remains the only canonical source of displayed text.

## Two timelines and exact time

Faster-Whisper reports word boundaries as seconds on the cleaned audio. The adapter converts each boundary exactly from the backend's decimal representation into `Fraction`, then quantizes once:

```text
cleaned_start_sample = floor(start_seconds × sample_rate)
cleaned_end_sample   = ceil(end_seconds × sample_rate)
```

Floor/ceil conservatively includes the observed word edges. An end boundary at most one sample beyond the WAV is clamped to the exact endpoint to tolerate decimal representation; larger overruns are rejected. Negative, empty, out-of-range, non-positive, or non-monotonic word intervals fail with a stable `STT_*` code.

The existing binary-search `TimelineMapper` then performs:

```text
cleaned sample (edit-map target) -> original sample (edit-map source)
```

Every `RecognizedWord` stores:

- `start_sample_cleaned` and `end_sample_cleaned`;
- `start_sample_original` and `end_sample_original`;
- exact cleaned `start_seconds` and `end_seconds` derived from samples;
- exact original second values derived from original samples;
- optional confidence.

Samples remain the sole timing authority. JSON seconds are objects with numerator, denominator, and a decimal rendering; no cumulative float arithmetic is used.

Before inference mapping, the service proves that cleaned sample rate, exact sample count, and SHA-256 equal the edit-map target. A tampered WAV or map is rejected. `recognition.json` records the cleaned hash, edit-map target hash, model fingerprint, backend version, device, compute type, beam size, temperature, and quantization policy without absolute paths.

## Deterministic inference profile

The technical default is CPU/int8, beam size 5, temperature 0.0. The adapter fixes:

- task `transcribe`;
- `word_timestamps=True`;
- `condition_on_previous_text=False`;
- `vad_filter=False`;
- `without_timestamps=False`.

Fixed model bytes, audio bytes, edit map, runtime, device, compute type, and settings define the reproducibility profile. Sample conversion and timeline mapping are deterministic. Native inference can still differ across runtime versions, hardware backends, or parallel floating-point implementations; therefore logical release comparisons must include the recorded provenance rather than claim cross-hardware byte identity.

## Supported models and manual preparation

MVP allows `tiny`, `base`, and `small`. No baseline model is silently selected. A complete Faster-Whisper/CTranslate2 directory can be prepared deliberately on a connected machine and copied to the offline application machine, for example as:

```text
models/
  tiny/
    config.json
    model.bin
    tokenizer.json
```

The official Faster-Whisper documentation explains that loading a model name downloads a model and that a converted model can be loaded from a local directory. Such download/conversion is a separate explicit preparation action; the application processing path does neither. Model files and caches must not be committed or placed in Stage output archives.

Developer dependency installation is handled only by the project lockfile:

```bash
uv sync --frozen
```

Faster-Whisper 1.2.x is MIT-licensed. The declared policy is `>=1.2.1,<2`, and the current `uv.lock` resolves 1.2.1. It is the only direct Stage 7 runtime dependency. Its transitive packages include native and platform-specific artifacts (notably CTranslate2 for inference and PyAV for media decoding), tokenizer/runtime libraries, numerical libraries, and `huggingface-hub`. The latter is present transitively, but this adapter neither imports it nor gives Faster-Whisper a remote model identifier; local directory preflight plus `local_files_only=True` define the processing path.

The dependency stack increases installer size and requires separate Windows/macOS packaging, signing, complete transitive license inventory, vulnerability review, and clean-machine/offline packaged smoke checks before release. Those packaging checks are not part of Stage 7 and remain open. No GPU libraries are added directly; CUDA execution requires a separately approved packaging profile. Updates must be deliberate lockfile changes followed by unit, real-model, offline, and packaged tests. Removal is architecturally contained to the `models` adapter and dependency declaration, but would remove the required STT capability.

## Configuration

`[models]` supports:

- `whisper_backend = "faster-whisper"`;
- `whisper_model = "tiny" | "base" | "small"`;
- `model_path` as an explicit local directory, or `model_root/<model>` through the application layer;
- `device = "cpu" | "cuda" | "auto"`;
- an allowlisted CTranslate2 `compute_type`;
- optional language code;
- beam size in `[1, 100]`;
- temperature in `[0, 1]`.

Configuration uses explicit TOML only. `.env` is not read. The developer CLI mirrors these settings as arguments.

## CLI and output

```bash
uv run --frozen python -m larp_audio_mvp.app.recognize_speech \
  CLEANED.wav EDIT_MAP.json \
  --work-directory ./work/recognition \
  --model tiny \
  --model-path /absolute/path/to/tiny \
  --device cpu \
  --compute-type int8 \
  --language en
```

On success the CLI atomically creates `recognition.json`, prints a summary without word text, and exits `0`. Expected model, backend, input, mapping, or output failures print a stable error code and exit `2`. A missing local model is always an error, never a download trigger.

## Limitations

- This is transcription timing, not forced alignment; word boundaries are model estimates.
- `recognition.json` intentionally contains ASR text evidence, so it is an internal working artifact and is not part of the final portable manifest by default.
- Model language support and timing accuracy are not yet benchmarked on the release corpus.
- CPU/GPU performance, memory, installer size, and packaged native library behavior are not yet release-qualified.
- Cancellation/progress and long-running model reuse are not implemented by this developer CLI.
- Direct STT on cleaned audio cannot certify cuts that were made before speech guards existed.
