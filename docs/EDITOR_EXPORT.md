# Universal WAV + SRT export

## Consumer workflow

After a successful run, **Export** asks only for an existing destination folder
and an optional base name. The default comes from the original audio filename.
Meaningful Unicode, Cyrillic, spaces, apostrophes, and ampersands are preserved;
only characters invalid on common filesystems are replaced.

One export publishes exactly:

- `<export_name>_audio.wav`;
- `<export_name>_subtitles.srt`.

There is no editor selector, frame-rate field, XML, project folder, script,
manifest, instructions, diagnostics, or ZIP in the consumer export. Import both
files at timeline zero in CapCut, Premiere Pro, DaVinci Resolve, Final Cut Pro,
or another editor that supports external SRT captions.

## Timing

The exporter consumes the validated v4 display model. Every cue is at most 45
characters, ordinary sentence-ending periods are hidden, ellipses and lexical
dots remain, and the immutable source span stays available in the processed
result. Each block keeps its real `cleaned_start_sample` and
`cleaned_end_sample` speech interval. Display timing is derived by the same
canonical function used by Preview and the subtitle table:

- non-final Preview interval: `[speech_start, next_speech_start)`;
- final Preview interval: `[speech_start, cleaned_audio_end)`;
- non-final SRT end: `next_start_ms - 1 ms`;
- final SRT end: `ceil(cleaned_total_samples × 1000 / sample_rate)`.

The first cue is not moved before its valid start. This creates continuous
coverage between existing cues and through the cleaned-audio tail without
modifying speech timing, recognition, alignment, pause removal, or cleaned WAV.
When millisecond precision cannot represent a positive cue, export fails rather
than inventing time.

## Validation and publication

The service reads the already validated cleaned-audio artifact and approved
`SubtitleDocument`; it does not rerun processing or segmentation. Before
publication it checks:

- WAV is PCM 16-bit, 48,000 Hz, with the expected channel count and exact frame
  count;
- subtitle sample rate and cleaned duration equal the WAV contract;
- SRT is UTF-8 without BOM, uses CRLF and standard timestamps;
- indices, v4 display text/45-character limit, monotonicity, positive durations, gapless
  boundaries, and final duration all match the source document.

A hidden staging directory is created inside the destination filesystem. The
validated pair is published through collision-failing hard links so existing
files are never overwritten. If publishing the second file fails, the first is
removed before returning a controlled error. Cancellation before publication
leaves no user file; staging is always removed.

If either target filename exists, both files use the next base (`name_2`,
`name_3`, …). The processed result remains read-only.

## Privacy and limitations

The two files contain audio samples and subtitle text only. They contain no run
ID, source/repository/model path, manifest, or diagnostic metadata. The export
does not create native CapCut drafts, Premiere/Resolve XML, editable caption
tracks, or timeline projects. Real editor import and synchronization remain a
manual acceptance check; structural WAV/SRT validation is not presented as
proof of a particular editor version.
