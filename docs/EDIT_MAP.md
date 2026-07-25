# Edit map and deterministic pause shortening

## Scope

Stage 6 takes an already canonical WAV plus normalized `PauseSegment` observations, decides which pause middles are eligible for shortening, creates one immutable `EditMap`, and renders a new canonical WAV from that map. No STT, alignment, subtitle, SRT, XML, GUI, or CapCut behavior is included.

After the map is built, it is the only authority for source-to-target time conversion. Renderer and `TimelineMapper` consume its spans; they do not independently recompute cumulative offsets.

This stage is a technical signal-only implementation. Every map carries `signal_only_pause_policy_without_stt_alignment`. It demonstrates deterministic shortening but is not yet the release safety gate that will combine speech timestamps, alignment confidence, and word guards.

## Shortening policy

The policy requires an explicit version and three integer millisecond values:

- `minimum_pause_to_shorten_ms`;
- `target_remaining_pause_ms`;
- `maximum_removed_per_pause_ms`.

There are no hidden defaults. Configuration requires:

- all three values together with `shortening_policy_version`;
- `target_remaining_pause_ms > 0`;
- `minimum_pause_to_shorten_ms > target_remaining_pause_ms`;
- `maximum_removed_per_pause_ms > 0`;
- `preserve_edge_silence = true` for Stage 6.

Milliseconds are converted once with integer ceiling:

```text
samples = ceil(milliseconds × sample_rate / 1000)
```

For each sorted non-overlapping pause:

1. a pause touching sample `0` or `source_total_samples` is preserved;
2. a pause whose length is less than or equal to the shortening threshold is preserved;
3. otherwise desired removal is `pause_length - target_remaining_pause`;
4. actual removal is `min(desired_removal, maximum_removed_per_pause)`;
5. the remaining samples are divided between the beginning and end of the pause;
6. only the exact center interval is marked `REMOVE`.

The policy never removes a whole pause, never extends outside a detected pause, and always retains samples on both sides of a shortened internal pause. When the maximum-removal cap applies, more than the target pause is retained.

## EditMap contract

`EditMap` contains:

- `schema_version` and `policy_version`;
- sample rate;
- exact source and target sample totals;
- source and target SHA-256;
- integer policy snapshot in milliseconds and derived samples;
- ordered `KEEP` and `REMOVE` spans;
- warnings.

Every serialized span stores:

- `source_start`, `source_end`;
- `target_start`, `target_end`;
- `removed_samples`;
- kind and reason.

A `KEEP` span has equal source and target lengths. A `REMOVE` span has `target_start == target_end`: it collapses to one cut anchor without fabricating target audio. Removal entries additionally store the original pause candidate and retained samples before and after the removed middle.

Example shape:

```json
{
  "kind": "remove",
  "source_start": 24000,
  "source_end": 43200,
  "target_start": 24000,
  "target_end": 24000,
  "removed_samples": 19200,
  "candidate": {
    "source_start": 19200,
    "source_end": 48000
  },
  "retained_before_samples": 4800,
  "retained_after_samples": 4800,
  "reason": "shorten_pause_middle"
}
```

Map construction validates that:

- source spans form a complete non-overlapping partition `[0, source_total)`;
- target KEEP spans form a continuous non-overlapping partition `[0, target_total)`;
- each REMOVE collapses at the current target cursor;
- `sum(removed_samples) == source_total - target_total`;
- all arithmetic uses integers.

An input with no eligible pauses produces an identity map with one KEEP span and no drift.

## TimelineMapper

`TimelineMapper` precomputes source and target span-start tuples and uses `bisect_right`. Each mapping query is `O(log n)`.

### Source to target

- Kept sample: affine mapping inside its KEEP span.
- Removed sample: maps deterministically to the removal's cut anchor.
- Source endpoint: maps to target endpoint.

### Target to source

- Every target sample belongs to one KEEP span and maps affinely to its source sample.
- At a cut anchor, the target sample is the first kept sample after the cut, so inverse mapping selects the post-cut source sample.
- Target endpoint maps to source endpoint.

This convention makes reverse mapping deterministic while acknowledging that removed source samples have no individual samples on the target timeline.

## WAV rendering

The renderer receives the completed logical map and selects only its KEEP source ranges with FFmpeg `atrim=start_sample=...:end_sample=...`. Each part receives `asetpts=N/SR/TB`; multiple parts are joined through the audio `concat` filter.

The renderer does not inspect pauses or policy values. Therefore the physical WAV cannot diverge because of a second independent cut calculation.

Output is written as a unique `.partial.wav` in the destination directory, reprobed, and published with `os.replace` only after validation confirms:

- WAV remains canonical;
- codec, sample format, sample rate, and channels match the source;
- exact output sample count equals `EditMap.output_total_samples`;
- target SHA-256 is available.

The source path cannot equal the destination path. Any FFmpeg, probe, format, or sample-count error removes the temporary file and does not publish the new WAV.

`edit_map.json` is also written through a same-directory temporary file and atomic replacement. It is persisted only after the renderer supplies target SHA-256.

## Technical CLI

```bash
uv run --frozen python -m larp_audio_mvp.app.remove_pauses INPUT.wav \
  --work-directory ./work/remove \
  --silence-threshold-db -50 \
  --minimum-pause-duration-ms 300 \
  --policy-version technical-v1 \
  --minimum-pause-to-shorten-ms 500 \
  --target-remaining-pause-ms 200 \
  --maximum-removed-per-pause-ms 1000
```

The CLI uses existing ffprobe, pause detector, policy, builder, renderer, and serializers. It creates `cleaned_audio.wav` and `edit_map.json`, then prints a short JSON summary. It is a developer tool, not the product GUI.

Both `ffmpeg` and `ffprobe` are required for the full CLI. Explicit and bundled paths follow the executable-resolution policy from audio ingestion.

## Limitations

- Signal silence alone cannot prove word safety; release use still requires STT/alignment guards.
- FFmpeg filter behavior and binary version remain part of reproducibility provenance.
- Large numbers of cuts increase filter-graph command size; a measured batching strategy may be needed later.
- Multi-channel/noncanonical sources must pass ingestion first.
- The map schema is versioned but no backward-compatibility migration framework is implemented yet.
