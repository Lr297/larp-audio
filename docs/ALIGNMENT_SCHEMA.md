# Alignment schema v2

## Stage 11.1 safe source metadata

`alignment.schema.v2` is retained. Pipeline-produced documents set script
`source_path` to a privacy-safe basename and may add optional `source_kind` and
`newline_style`. This is an additive reader-compatible refinement: exact text,
SHA-256, tokens, ASR classification, and both timelines are unchanged. Legacy
v2 documents without the optional fields remain readable.

`PublishedSourceReference` is a pipeline boundary contract rather than an
alignment schema object. It carries safe display name, logical role, content
SHA-256, source kind, original extension, and optional BOM/newline metadata.
Absolute runtime input paths are never published.

## Назначение

`alignment.schema.v2` — строго проверяемый результат script-to-ASR alignment и безопасный вход для будущего subtitle chunker. Оригинальный скрипт остаётся единственным источником отображаемого текста. ASR-текст хранится только как timing/comparison evidence.

Stage 8 schema `"1"` не содержит достаточных данных для полной проверки provenance и timeline mapping. Reader явно отклоняет её с `UNSUPPORTED_ALIGNMENT_SCHEMA`; автоматическая миграция не выполняется. Повторное выравнивание из исходных `script.txt`, `recognition.json` и `edit_map.json` является безопасным путём обновления.

## Верхний уровень

V2 содержит:

- `schema_version = "alignment.schema.v2"`;
- `sample_rate`;
- точный `script` metadata и полный массив обратимых `tokens`;
- полный canonical `recognition` из Stage 7;
- полный canonical `edit_map` из Stage 6;
- `aligned_words` типа `AlignedScriptWord`;
- `unmatched_asr_words`;
- `rejected_asr_evidence`;
- пересчитываемые `diagnostics`;
- `warnings` и отсортированный `configuration` snapshot.

Встраивание recognition и edit map не создаёт новые параллельные контракты: serializer использует существующие Stage 7/6 serializers, а reader восстанавливает существующие `RecognitionResult` и `EditMap`. Это позволяет standalone-reader проверить every cleaned-to-original boundary существующим `TimelineMapper`.

## Канонический aligned word

`AlignedScriptWord` — единственный контракт выровненного слова оригинального скрипта. Старое имя `AlignedWord` является deprecated alias на тот же класс, а не самостоятельной моделью.

Запись содержит:

- идентичность script word: `script_word_index`, `token_index`, `exact_text`, `char_start`, `char_end`;
- cleaned/original integer sample boundaries или `null`;
- независимые `match_type` и `timing_status`;
- только принятые `matched_recognition_indices`;
- stable `alignment_operation_id` для принятой операции;
- ASR confidence только для реального принятого evidence;
- `text_similarity` и `alignment_score` только для принятого текстового сопоставления;
- left/right script anchors для интерполяции;
- warnings.

Интерполированное слово всегда имеет пустой `matched_recognition_indices`, null ASR confidence, null operation/score/similarity и два проверяемых anchor indices. Unresolved word не имеет временных границ или ASR provenance.

## Полная ASR-классификация

Каждый recognition index от `0` до `total_asr_words - 1` входит ровно в одну категорию:

1. Accepted — присутствует в `matched_recognition_indices` принятого match и определяет его текстовое сопоставление и время.
2. Unmatched — присутствует в `unmatched_asr_words`, если DP классифицировал ASR observation как insertion без попытки принятого сопоставления.
3. Rejected — присутствует в `rejected_asr_evidence`, если observation участвовал в отклонённом substitution или split/merge.

Категории не пересекаются и вместе покрывают все индексы. `classified_asr_words` равно размеру объединения, а `provenance_complete` истинно только при точном покрытии.

Accepted index может встречаться у нескольких script words исключительно внутри одной валидной `many_script_to_one_asr` operation group. Группа использует один ASR index, последовательные script indices и смежные диапазоны, которые без потерь образуют детерминированное целочисленное разбиение ASR interval.

## Rejected evidence

Каждый элемент `rejected_asr_evidence` immutable-контракта хранит:

- `recognition_index` и точный ASR `text`;
- cleaned/original sample boundaries;
- исходный ASR `confidence` либо null;
- `rejection_reason`;
- `related_script_word_indices`;
- `attempted_match_type`;
- `attempted_alignment_operation_id`.

Поддерживаемые причины v2:

- `substitution_not_accepted`;
- `timing_distribution_impossible`.

Rejected evidence никогда не становится итоговым текстом и не остаётся в `matched_recognition_indices` после interpolation.

## Strict reader

`read_alignment()` отклоняет malformed JSON и неизвестную schema, затем реконструирует доменные контракты и выполняет строгую семантическую валидацию. Проверяются:

- integer numerator/denominator, положительный denominator, finite и точный decimal для каждого rational;
- exact script SHA-256 с учётом UTF-8 BOM metadata, character/line counts;
- непрерывное покрытие exact text каноническими обратимыми токенами;
- один aligned word на каждый word token и полное совпадение identity/offsets;
- допустимые комбинации match/timing/provenance/confidence;
- последовательность, уникальность и полная классификация ASR indices;
- one-to-many continuity и many-to-one operation groups;
- bounds, monotonicity и соответствие каждого cleaned→original boundary существующему `TimelineMapper`;
- observed/union/distributed/interpolated timing rules;
- совместимость embedded recognition/edit map metadata и hashes;
- точное равенство сохранённых diagnostics заново пересчитанным значениям.

Любая ошибка преобразуется в контролируемый `AlignmentSerializationError` либо `AlignmentValidationError`. Reader не исправляет повреждённую статистику молча.

## Diagnostics

Reader пересчитывает:

- `total_script_words`, `total_asr_words`;
- exact, normalized, fuzzy и split/merge match counts;
- substitutions, interpolated и unresolved word counts;
- unmatched/rejected/classified ASR counts и `provenance_complete`;
- `observed_timing_coverage`, `total_timing_coverage`, `text_alignment_coverage`.

Coverage хранится как проверяемая rational value. Observed coverage включает только `timing_status=observed`; total timing coverage включает все разрешённые интервалы; text alignment coverage включает только принятые exact/normalized/fuzzy/split-merge matches.

## Детерминированная запись

JSON записывается в UTF-8 с `ensure_ascii=false`, сортированными ключами, стабильными массивами, двумя пробелами indent и одним завершающим LF. Non-finite numbers запрещены. Сначала создаётся соседний `.partial.json`, затем после flush/fsync выполняется `os.replace`; временный файл удаляется и после ошибки.

Будущий `SubtitleChunker` Protocol принимает целый validated `AlignmentResult`, чтобы не потерять exact text, punctuation/whitespace tokens, char offsets и timing/provenance. Stage 8.1 не реализует subtitle chunking.
