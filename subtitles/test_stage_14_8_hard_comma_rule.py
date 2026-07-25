import tempfile
import json
from pathlib import Path

from larp_audio_mvp.alignment import read_script
from larp_audio_mvp.alignment.tokenizer import tokenize_script
from larp_audio_mvp.config import AlignmentSettings, SubtitleSettings
from larp_audio_mvp.core.contracts import (
    EditKind, EditMap, EditSpan, RecognitionResult,
    RecognizedWord, ScriptTokenKind, SampleRange
)
from larp_audio_mvp.alignment.service import ScriptAlignmentService
from larp_audio_mvp.subtitles.service import SubtitleGenerationService
from larp_audio_mvp.subtitles.serialization import read_subtitle_document
from larp_audio_mvp.alignment.serialization import alignment_to_dict

def _make_alignment_bytes(text: str, word_duration=350, sample_rate=1000) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "script.txt"
        script_path.write_text(text, encoding="utf-8")
        document = read_script(script_path)
        tokens = tokenize_script(text)
        words = tuple(t for t in tokens if t.kind is ScriptTokenKind.WORD)
        starts = tuple(500 + i * 1000 for i in range(len(words)))
        total = max(starts[-1] + word_duration if starts else 0, sample_rate) + sample_rate
        edit_map = EditMap(
            schema_version="1", policy_version="test-v1", sample_rate=sample_rate,
            source_total_samples=total, output_total_samples=total,
            source_sha256="a" * 64, output_sha256="b" * 64,
            spans=(EditSpan(EditKind.KEEP, SampleRange(0, total), SampleRange(0, total), reason="identity"),),
        )
        recognized = tuple(
            RecognizedWord(
                text=t.exact_text, sample_rate=sample_rate,
                start_sample_cleaned=starts[i], end_sample_cleaned=starts[i] + word_duration,
                start_sample_original=starts[i], end_sample_original=starts[i] + word_duration,
                confidence=0.9,
            )
            for i, t in enumerate(words)
        )
        recognition = RecognitionResult(
            schema_version="1", backend="faster-whisper", model="tiny",
            language=None, sample_rate=sample_rate,
            duration_samples_cleaned=total, duration_samples_original=total,
            words=recognized, metadata=(("cleaned_audio_sha256", "b" * 64),),
        )
        alignment = ScriptAlignmentService(AlignmentSettings()).align(document, recognition, edit_map)
        return json.dumps(alignment_to_dict(alignment)).encode("utf-8")

def test_hard_comma_rule_exhaustive():
    cases = [
        (
            "When I sneezed, nothing happened",
            ["When I sneezed", "nothing happened"]
        ),
        (
            "Women point the finger at age, at childbirth, at weak pelvic floors",
            ["Women point the finger at age", "at childbirth", "at weak pelvic floors"]
        ),
        (
            "She tried pills, exercises, and heat therapy",
            ["She tried pills", "exercises", "and heat therapy"]
        ),
        (
            "I saw an apple, or maybe a pear, sitting there.",
            ["I saw an apple", "or maybe a pear", "sitting there"]
        ),
        (
            "Wait, wait, wait, what?",
            ["Wait", "wait", "wait", "what?"]
        )
    ]
    
    for text, expected_cues in cases:
        alignment_bytes = _make_alignment_bytes(text)
        
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            alignment_path = d / "alignment.json"
            alignment_path.write_bytes(alignment_bytes)
            blocks_path = d / "blocks.json"
            srt_path = d / "output.srt"
            
            service = SubtitleGenerationService()
            service.generate(
                alignment_path=alignment_path,
                blocks_output=blocks_path,
                srt_output=srt_path,
                settings=SubtitleSettings(),
            )
            
            # Check Preview cues (document output)
            doc = read_subtitle_document(blocks_path)
            cues = [b.display_text_plain for b in doc.blocks]
            assert cues == expected_cues, f"Expected {expected_cues}, got {cues}"
            
            # Ensure no comma is in any cue
            for cue in cues:
                assert "," not in cue, f"Comma found in cue: {cue}"
                
            # Check SRT output
            srt_content = srt_path.read_text(encoding="utf-8")
            
            # Check original script remains unchanged
            assert doc.exact_script_text == text, "Original script text was mutated"
