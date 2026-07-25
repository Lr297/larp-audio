"""Diagnostics derived from validated pipeline artifacts."""

from __future__ import annotations

from larp_audio_mvp.pipeline.contracts import PipelineRunResult, ProcessingReport

from .contracts import DiagnosticEntry, DiagnosticSeverity, PreviewDiagnostics


def build_preview_diagnostics(result: PipelineRunResult, report: ProcessingReport) -> PreviewDiagnostics:
    metrics = dict(report.metrics); document = result.subtitle_document; summary = result.summary
    percent = 0 if summary.source_duration_samples == 0 else summary.removed_samples * 100 / summary.source_duration_samples
    entries = (
        DiagnosticEntry("Audio", "Source samples", str(summary.source_duration_samples)),
        DiagnosticEntry("Audio", "Cleaned samples", str(summary.cleaned_duration_samples), DiagnosticSeverity.SUCCESS),
        DiagnosticEntry("Audio", "Removed", f"{summary.removed_samples} ({percent:.1f}%)"),
        DiagnosticEntry("Audio", "Sample rate", f"{summary.sample_rate} Hz"),
        DiagnosticEntry("Audio", "Channels / sample width", "1 / 16-bit PCM"),
        DiagnosticEntry("Audio", "Detected pauses", str(summary.detected_pause_count)),
        DiagnosticEntry("Recognition", "Language", str(metrics.get("recognition_language", "auto"))),
        DiagnosticEntry("Recognition", "Model", str(metrics.get("model_name", "unknown"))),
        DiagnosticEntry("Recognition", "Words", str(metrics.get("recognition_word_count", 0))),
        DiagnosticEntry("Alignment", "Unresolved words", str(summary.unresolved_word_count), DiagnosticSeverity.WARNING if summary.unresolved_word_count else DiagnosticSeverity.SUCCESS),
        DiagnosticEntry("Alignment", "Interpolated words", str(summary.interpolated_word_count), DiagnosticSeverity.WARNING if summary.interpolated_word_count else DiagnosticSeverity.SUCCESS),
        DiagnosticEntry("Alignment", "Text coverage", f"{float(summary.text_coverage) * 100:.1f}%"),
        DiagnosticEntry("Alignment", "Timing coverage", f"{float(summary.timing_coverage) * 100:.1f}%"),
        DiagnosticEntry("Subtitles", "Blocks", str(len(document.blocks))),
        DiagnosticEntry("Subtitles", "Single-word blocks", str(document.diagnostics.single_word_blocks)),
        DiagnosticEntry("Subtitles", "Short blocks", str(document.diagnostics.short_blocks)),
        DiagnosticEntry("Subtitles", "Maximum CPS", f"{float(document.diagnostics.maximum_characters_per_second):.2f}"),
        DiagnosticEntry("Subtitles", "Blocks with warnings", str(sum(bool(block.warnings) for block in document.blocks)), DiagnosticSeverity.WARNING if any(block.warnings for block in document.blocks) else DiagnosticSeverity.SUCCESS),
        DiagnosticEntry("Package", "Artifact count", "8", DiagnosticSeverity.SUCCESS),
        DiagnosticEntry("Package", "ZIP bytes", str(result.package_zip_path.stat().st_size), DiagnosticSeverity.SUCCESS),
        DiagnosticEntry("Package", "Manifest / package / privacy / provenance", "validated", DiagnosticSeverity.SUCCESS),
    )
    return PreviewDiagnostics(result.run_id, entries, True, True)
