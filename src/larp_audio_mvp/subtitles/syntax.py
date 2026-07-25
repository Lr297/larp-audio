"""Local syntax features and boundary legality for English subtitles.

The primary implementation uses the bundled ``en_core_web_sm`` pipeline.
Every parser token is mapped back to an immutable original-script word span;
parser-normalized text is never used for display.  A deterministic fallback is
available only as a controlled recovery path and is exposed in diagnostics.
"""

from __future__ import annotations

import importlib
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter_ns
from typing import Any, ClassVar


class SyntaxAnalyzerMode(StrEnum):
    SPACY_EN_CORE_WEB_SM = "spacy_en_core_web_sm"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class BoundaryLegality(StrEnum):
    LEGAL = "legal"
    DISCOURAGED = "discouraged"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class SyntaxTokenFeature:
    word_index: int
    original_text: str
    display_text: str
    lemma: str
    char_start: int
    char_end: int
    source_token_index: int
    timing_reference: int
    punctuation_type: str | None
    part_of_speech: str
    fine_grained_tag: str
    dependency_relation: str
    syntactic_head_index: int | None
    sentence_index: int
    clause_membership: int
    is_function_word: bool
    is_particle: bool
    is_degree_modifier: bool
    is_coordinated_list_member: bool
    protected_span_ids: tuple[str, ...]
    parser_token_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SyntaxAnalysis:
    mode: SyntaxAnalyzerMode
    model_name: str
    model_version: str | None
    parser_initialization_nanoseconds: int
    parse_nanoseconds: int
    features: tuple[SyntaxTokenFeature, ...]
    sentence_boundaries: frozenset[int]
    clause_boundaries: frozenset[int]
    list_item_boundaries: frozenset[int]
    protected_by_category: tuple[tuple[str, frozenset[int]], ...]
    legal_boundaries: frozenset[int]
    discouraged_boundaries: frozenset[int]
    forbidden_boundaries: frozenset[int]
    warnings: tuple[str, ...] = ()

    def boundaries_for(self, category: str) -> frozenset[int]:
        return dict(self.protected_by_category).get(category, frozenset())


_FUNCTION_POS = frozenset({"ADP", "AUX", "CCONJ", "DET", "PART", "PRON", "SCONJ"})
_SUBORDINATORS = frozenset(
    {"after", "although", "as", "because", "before", "if", "since", "unless", "until", "when", "where", "whether", "while"}
)
_DEGREE_MODIFIERS = frozenset(
    {"almost", "even", "far", "less", "more", "much", "quite", "rather", "slightly", "so", "too", "very"}
)
_TEMPORAL_MODIFIERS = frozenset(
    {"immediately", "just", "long", "right", "shortly", "soon"}
)
_PARTICLES = frozenset({"away", "back", "down", "off", "on", "out", "over", "through", "up"})
_DETERMINERS = frozenset(
    {"a", "an", "her", "his", "its", "my", "our", "the", "their", "these", "this", "those", "your"}
)
_AUXILIARIES = frozenset(
    {"am", "are", "be", "been", "being", "can", "could", "did", "do", "does", "had", "has", "have", "is", "may", "might", "must", "shall", "should", "was", "were", "will", "would"}
)
_PREPOSITIONS = frozenset(
    {"after", "against", "around", "at", "before", "by", "during", "for", "from", "in", "into", "of", "on", "onto", "through", "to", "under", "with", "without"}
)
_OBJECT_PRONOUNS = frozenset({"her", "him", "it", "me", "them", "us", "you"})
_NUMBER_UNITS = frozenset(
    {"day", "days", "hour", "hours", "minute", "minutes", "month", "months", "percent", "second", "seconds", "week", "weeks", "year", "years", "%"}
)
_WH_COMPLEMENTS = frozenset({"how", "what", "where", "which", "who", "why"})
_LIST_INTRODUCERS = frozenset({"including", "like"})


class LocalEnglishSyntaxAnalyzer:
    """Lazy reusable spaCy analyzer with explicit deterministic fallback."""

    _pipeline: ClassVar[Any | None] = None
    _pipeline_version: ClassVar[str | None] = None
    _initialization_ns: ClassVar[int] = 0
    _initialization_report_pending: ClassVar[bool] = False
    _load_error: ClassVar[BaseException | None] = None
    _model_module: ClassVar[Any | None] = None
    _module_import_error: ClassVar[BaseException | None] = None
    _analysis_cache: ClassVar[OrderedDict[tuple[object, ...], SyntaxAnalysis]] = OrderedDict()
    _analysis_cache_limit: ClassVar[int] = 8
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, *, allow_fallback: bool = True) -> None:
        self.allow_fallback = allow_fallback

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._pipeline = None
            cls._pipeline_version = None
            cls._initialization_ns = 0
            cls._initialization_report_pending = False
            cls._load_error = None
            cls._analysis_cache.clear()

    @classmethod
    def prepare_runtime(cls) -> bool:
        """Import native parser modules before a Qt worker is started.

        The model pipeline and weights remain lazy.  Importing spaCy's native
        runtime in the GUI thread avoids a macOS/Python cold-import stall in a
        newly started ``QThread``; headless callers can ignore this method.
        """

        if cls._model_module is not None:
            return True
        if cls._module_import_error is not None:
            return False
        with cls._lock:
            if cls._model_module is not None:
                return True
            try:
                model_module = importlib.import_module("en_core_web_sm")
                # spaCy 3.8 populates its component registry on first model
                # load by importing several optional language modules.  Do
                # that native-runtime registration on the controller thread;
                # the actual English model and BLAS-backed weights are still
                # constructed lazily inside the processing worker.
                spacy_util = importlib.import_module("spacy.util")
                spacy_util.registry.ensure_populated()
                cls._model_module = model_module
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                cls._module_import_error = exc
                return False
        return True

    @classmethod
    def _claim_initialization_duration(cls) -> int:
        with cls._lock:
            if not cls._initialization_report_pending:
                return 0
            cls._initialization_report_pending = False
            return cls._initialization_ns

    @classmethod
    def _load_pipeline(cls) -> tuple[Any, int, str | None]:
        if cls._pipeline is not None:
            return cls._pipeline, 0, cls._pipeline_version
        if cls._load_error is not None:
            raise RuntimeError("bundled English syntax pipeline is unavailable") from cls._load_error
        if not cls.prepare_runtime():
            raise RuntimeError("bundled English syntax pipeline is unavailable") from cls._module_import_error
        with cls._lock:
            if cls._pipeline is not None:
                return cls._pipeline, 0, cls._pipeline_version
            started = perf_counter_ns()
            try:
                model = cls._model_module
                if model is None:
                    raise RuntimeError("bundled English syntax module was not prepared")
                pipeline = model.load()
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                cls._load_error = exc
                raise RuntimeError("bundled English syntax pipeline is unavailable") from exc
            elapsed = perf_counter_ns() - started
            cls._pipeline = pipeline
            cls._pipeline_version = getattr(model, "__version__", None)
            cls._initialization_ns = elapsed
            cls._initialization_report_pending = True
            return pipeline, elapsed, cls._pipeline_version

    def analyze(self, exact_text: str, words: Sequence[object]) -> SyntaxAnalysis:
        cache_key = _analysis_cache_key(exact_text, words)
        with self._lock:
            cached = self._analysis_cache.get(cache_key)
            if cached is not None:
                self._analysis_cache.move_to_end(cache_key)
                return cached
        try:
            pipeline, _initialization_ns, version = self._load_pipeline()
            initialization_ns = self._claim_initialization_duration()
            started = perf_counter_ns()
            document = pipeline(exact_text)
            parse_ns = perf_counter_ns() - started
            result = _analysis_from_spacy(
                exact_text,
                words,
                document,
                initialization_ns=initialization_ns,
                parse_ns=parse_ns,
                model_version=version,
            )
        except (RuntimeError, OSError, ValueError, IndexError) as exc:
            if not self.allow_fallback:
                raise
            started = perf_counter_ns()
            result = _fallback_analysis(exact_text, words)
            elapsed = perf_counter_ns() - started
            result = SyntaxAnalysis(
                mode=result.mode,
                model_name=result.model_name,
                model_version=result.model_version,
                parser_initialization_nanoseconds=0,
                parse_nanoseconds=elapsed,
                features=result.features,
                sentence_boundaries=result.sentence_boundaries,
                clause_boundaries=result.clause_boundaries,
                list_item_boundaries=result.list_item_boundaries,
                protected_by_category=result.protected_by_category,
                legal_boundaries=result.legal_boundaries,
                discouraged_boundaries=result.discouraged_boundaries,
                forbidden_boundaries=result.forbidden_boundaries,
                warnings=(f"full syntax analyzer unavailable; deterministic fallback used ({type(exc).__name__})",),
            )
        with self._lock:
            self._analysis_cache[cache_key] = result
            self._analysis_cache.move_to_end(cache_key)
            while len(self._analysis_cache) > self._analysis_cache_limit:
                self._analysis_cache.popitem(last=False)
        return result


def _analysis_cache_key(
    exact_text: str, words: Sequence[object]
) -> tuple[object, ...]:
    return (
        exact_text,
        tuple(
            (
                int(getattr(word, "char_start")),
                int(getattr(word, "char_end")),
                str(getattr(word, "exact_text")),
                int(getattr(word, "token_index", index)),
                int(getattr(word, "script_word_index", index)),
            )
            for index, word in enumerate(words)
        ),
    )


def _analysis_from_spacy(
    exact_text: str,
    words: Sequence[object],
    document: Any,
    *,
    initialization_ns: int,
    parse_ns: int,
    model_version: str | None,
) -> SyntaxAnalysis:
    count = len(words)
    token_to_word: dict[int, int] = {}
    word_to_tokens: list[list[Any]] = [[] for _ in words]
    cursor = 0
    for token in document:
        if token.is_space:
            continue
        token_start = int(token.idx)
        token_end = token_start + len(token.text)
        while cursor < count and int(getattr(words[cursor], "char_end")) <= token_start:
            cursor += 1
        probe = cursor
        while probe < count and int(getattr(words[probe], "char_start")) < token_end:
            word_start = int(getattr(words[probe], "char_start"))
            word_end = int(getattr(words[probe], "char_end"))
            if not token.is_punct and token_end > word_start and token_start < word_end:
                token_to_word[int(token.i)] = probe
                word_to_tokens[probe].append(token)
            probe += 1

    categories: dict[str, set[int]] = {
        "auxiliary_verb": set(),
        "verb_particle": set(),
        "verb_object": set(),
        "preposition_object": set(),
        "adjective_noun": set(),
        "compound_noun": set(),
        "degree_modifier": set(),
        "temporal_connector": set(),
        "number_unit": set(),
        "proper_name": set(),
        "determiner_noun": set(),
        "subordinator_clause": set(),
        "or_not": set(),
        "wh_clause": set(),
    }
    span_ids_by_word: list[set[str]] = [set() for _ in words]

    def protect(left_word: int, right_word: int, category: str, label: str) -> None:
        if left_word == right_word or min(left_word, right_word) < 0 or max(left_word, right_word) >= count:
            return
        start, end = sorted((left_word, right_word))
        char_start = int(getattr(words[start], "char_start"))
        char_end = int(getattr(words[end], "char_end"))
        if len(exact_text[char_start:char_end].strip()) > 45:
            return
        categories[category].update(range(start + 1, end + 1))
        span_id = f"{category}:{label}:{start}-{end}"
        for index in range(start, end + 1):
            span_ids_by_word[index].add(span_id)

    for token in document:
        word_index = token_to_word.get(int(token.i))
        head_index = token_to_word.get(int(token.head.i))
        if word_index is None or head_index is None or word_index == head_index:
            continue
        dep = token.dep_.lower()
        label = str(token.i)
        if dep in {"aux", "auxpass", "neg"}:
            protect(word_index, head_index, "auxiliary_verb", label)
        elif dep in {"prt"}:
            protect(word_index, head_index, "verb_particle", label)
        elif (
            dep in {"dobj", "iobj", "obj", "dative", "attr", "oprd"}
            and token.head.pos_ in {"VERB", "AUX", "ADJ"}
        ):
            object_words = sorted(
                {
                    token_to_word[int(item.i)]
                    for item in token.subtree
                    if int(item.i) in token_to_word
                }
            )
            if object_words:
                protect(object_words[0], object_words[-1], "verb_object", label)
                if object_words[0] == head_index + 1:
                    protect(head_index, object_words[0], "verb_object", label)
        elif dep in {"amod", "acomp"}:
            protect(word_index, head_index, "adjective_noun", label)
        elif dep in {"compound", "poss", "nmod"}:
            protect(word_index, head_index, "compound_noun", label)
        elif dep == "det":
            protect(word_index, head_index, "determiner_noun", label)
        elif dep in {"nummod", "quantmod"} and token.head.pos_ in {"NOUN", "PROPN", "SYM"}:
            protect(word_index, head_index, "number_unit", label)
        elif dep == "mark":
            # The subordinator belongs to the clause opening. Protecting the
            # first following boundary avoids a stranded marker without
            # forcing an arbitrarily long whole clause into one cue.
            if word_index + 1 < count:
                protect(word_index, word_index + 1, "subordinator_clause", label)
        elif dep == "advmod" and (
            token.lemma_.casefold() in _DEGREE_MODIFIERS
            or token.head.pos_ in {"ADJ", "ADV"}
        ):
            protect(word_index, head_index, "degree_modifier", label)

        if dep in {"pobj", "pcomp"} and token.head.dep_.lower() in {"prep", "agent"}:
            prep_index = token_to_word.get(int(token.head.i))
            if prep_index is not None:
                protect(prep_index, word_index, "preposition_object", label)
                governing_index = token_to_word.get(int(token.head.head.i))
                if (
                    governing_index is not None
                    and prep_index == governing_index + 1
                    and token.head.head.pos_ in {"VERB", "AUX", "ADJ"}
                ):
                    protect(governing_index, prep_index, "verb_object", label)

    # Statistical parsers sometimes tag an idiomatic particle as ADP/prep.
    # This generic dependency shape protects verb + short prepositional object,
    # not any literal word pair.
    for token in document:
        if token.dep_.lower() not in {"prep", "agent"} or token.head.pos_ not in {"VERB", "AUX", "ADJ"}:
            continue
        left = token_to_word.get(int(token.head.i))
        right = token_to_word.get(int(token.i))
        if left is not None and right is not None and right == left + 1:
            category = "verb_particle" if token.lemma_.casefold() in _PARTICLES else "verb_object"
            protect(left, right, category, str(token.i))

    # Named entities and consecutive proper nouns form compact protected spans.
    for entity in document.ents:
        indices = sorted({token_to_word[i] for i in range(int(entity.start), int(entity.end)) if i in token_to_word})
        if len(indices) >= 2:
            protect(indices[0], indices[-1], "proper_name", f"ent{entity.start}")
    for position in range(1, count):
        left_tokens = word_to_tokens[position - 1]
        right_tokens = word_to_tokens[position]
        if left_tokens and right_tokens and left_tokens[-1].pos_ == right_tokens[0].pos_ == "PROPN":
            protect(position - 1, position, "proper_name", f"propn{position}")

        left_key = str(getattr(words[position - 1], "exact_text")).casefold().strip(".,!?;:\"'()[]{}")
        right_key = str(getattr(words[position], "exact_text")).casefold().strip(".,!?;:\"'()[]{}")
        left_pos = left_tokens[-1].pos_ if left_tokens else ""
        if right_key in {"before", "after", "than", "when"} and (
            left_key in _TEMPORAL_MODIFIERS | _DEGREE_MODIFIERS or left_pos in {"ADV", "ADJ"}
        ):
            protect(position - 1, position, "temporal_connector", f"temporal{position}")
        if (_looks_numeric(left_key) and (right_key in _NUMBER_UNITS or right_key == "%")):
            protect(position - 1, position, "number_unit", f"number{position}")
        if _looks_numeric(left_key) and right_key == "of":
            protect(position - 1, position, "number_unit", f"quantified{position}")

    # Compact correlative and WH-complement constructions are guardrails.
    # They prevent illegal cuts but never propose a cue by themselves.
    keys = [
        str(getattr(word, "exact_text")).casefold().strip(".,!?;:\"'()[]{}")
        for word in words
    ]
    for position in range(1, count):
        if (
            keys[position] == "or"
            and position + 1 < count
            and keys[position + 1] == "not"
        ):
            protect(position - 1, position + 1, "or_not", f"or-not{position}")
        if (
            keys[position - 1] in _WH_COMPLEMENTS
        ):
            protect(
                position - 1,
                position,
                "wh_clause",
                f"wh-complement{position}",
            )

    sentence_boundaries: set[int] = set()
    sentence_index_by_token: dict[int, int] = {}
    for sentence_index, sentence in enumerate(document.sents):
        mapped = sorted({token_to_word[int(token.i)] for token in sentence if int(token.i) in token_to_word})
        for token in sentence:
            sentence_index_by_token[int(token.i)] = sentence_index
        if mapped and mapped[-1] + 1 < count:
            sentence_boundaries.add(mapped[-1] + 1)
    for position in range(1, count):
        separator = exact_text[
            int(getattr(words[position - 1], "char_end")):
            int(getattr(words[position], "char_start"))
        ]
        if any(mark in separator for mark in (".", "?", "!", "…", "\n", "\r")):
            sentence_boundaries.add(position)

    clause_boundaries: set[int] = set()
    for token in document:
        word_index = token_to_word.get(int(token.i))
        if word_index is None:
            continue
        if token.dep_.lower() in {"advcl", "ccomp", "xcomp", "relcl", "conj"} and word_index > 0:
            clause_boundaries.add(word_index)
        if token.dep_.lower() == "mark" and word_index > 0:
            clause_boundaries.add(word_index)

    list_boundaries = _spacy_list_boundaries(document, token_to_word, exact_text, words, word_to_tokens)
    demoted_boundaries = _demote_incompatible_protected_runs(
        exact_text,
        words,
        categories,
        mandatory_boundaries=sentence_boundaries | list_boundaries,
    )
    protected = set().union(*categories.values())
    all_boundaries = set(range(1, count))
    forbidden = frozenset(protected - sentence_boundaries - list_boundaries)
    discouraged: set[int] = set(demoted_boundaries)
    for position in all_boundaries - set(forbidden):
        left = word_to_tokens[position - 1][-1] if word_to_tokens[position - 1] else None
        right = word_to_tokens[position][0] if word_to_tokens[position] else None
        if left is not None and _requires_continuation(left):
            discouraged.add(position)
        if right is not None and _is_stranded_beginning(right):
            discouraged.add(position)
    discouraged.difference_update(sentence_boundaries | list_boundaries | clause_boundaries)

    features: list[SyntaxTokenFeature] = []
    list_member_words = _list_member_words(document, token_to_word)
    for word_index, word in enumerate(words):
        tokens = word_to_tokens[word_index]
        primary = _primary_token(tokens, token_to_word, word_index)
        if primary is None:
            key = str(getattr(word, "exact_text")).casefold()
            pos, tag, dep, lemma, head, sentence_index = _fallback_tag(key), "", "dep", key, None, 0
            parser_indices: tuple[int, ...] = ()
        else:
            pos, tag, dep, lemma = primary.pos_, primary.tag_, primary.dep_, primary.lemma_
            head = token_to_word.get(int(primary.head.i))
            sentence_index = sentence_index_by_token.get(int(primary.i), 0)
            parser_indices = tuple(int(token.i) for token in tokens)
        exact = str(getattr(word, "exact_text"))
        key = exact.casefold().strip(".,!?;:\"'()[]{}")
        features.append(
            SyntaxTokenFeature(
                word_index=word_index,
                original_text=exact,
                display_text=exact,
                lemma=lemma,
                char_start=int(getattr(word, "char_start")),
                char_end=int(getattr(word, "char_end")),
                source_token_index=int(getattr(word, "token_index", word_index)),
                timing_reference=int(getattr(word, "script_word_index", word_index)),
                punctuation_type=_punctuation_after(exact_text, int(getattr(word, "char_end"))),
                part_of_speech=pos,
                fine_grained_tag=tag,
                dependency_relation=dep,
                syntactic_head_index=head,
                sentence_index=sentence_index,
                clause_membership=sentence_index,
                is_function_word=pos in _FUNCTION_POS,
                is_particle=dep.lower() == "prt" or key in _PARTICLES,
                is_degree_modifier=key in _DEGREE_MODIFIERS,
                is_coordinated_list_member=word_index in list_member_words,
                protected_span_ids=tuple(sorted(span_ids_by_word[word_index])),
                parser_token_indices=parser_indices,
            )
        )

    return SyntaxAnalysis(
        mode=SyntaxAnalyzerMode.SPACY_EN_CORE_WEB_SM,
        model_name="en_core_web_sm",
        model_version=model_version,
        parser_initialization_nanoseconds=initialization_ns,
        parse_nanoseconds=parse_ns,
        features=tuple(features),
        sentence_boundaries=frozenset(sentence_boundaries),
        clause_boundaries=frozenset(clause_boundaries),
        list_item_boundaries=frozenset(list_boundaries),
        protected_by_category=tuple((name, frozenset(values)) for name, values in sorted(categories.items())),
        legal_boundaries=frozenset(all_boundaries - set(forbidden) - discouraged),
        discouraged_boundaries=frozenset(disccouraged for disccouraged in discouraged),
        forbidden_boundaries=forbidden,
    )


_PROTECTION_DAMAGE = {
    "auxiliary_verb": 100,
    "verb_particle": 100,
    "verb_object": 65,
    "preposition_object": 95,
    "adjective_noun": 90,
    "compound_noun": 95,
    "degree_modifier": 85,
    "temporal_connector": 95,
    "number_unit": 100,
    "proper_name": 100,
    "determiner_noun": 80,
    "subordinator_clause": 95,
    "or_not": 100,
    "wh_clause": 95,
}


def _demote_incompatible_protected_runs(
    exact_text: str,
    words: Sequence[object],
    categories: dict[str, set[int]],
    *,
    mandatory_boundaries: set[int],
) -> frozenset[int]:
    """Make the protection graph compatible with the 45-character limit.

    Independently valid dependency spans can overlap into a connected unit
    longer than one legal cue.  Such a unit cannot be protected in full.  A
    bounded dynamic program chooses the least damaging internal cut(s), with
    stable left-to-right tie-breaking, and demotes only those cuts from
    ``forbidden`` to ``discouraged``.  This is structural and contains no
    phrase-specific exceptions.
    """

    protected = set().union(*categories.values()) - mandatory_boundaries
    if not protected:
        return frozenset()
    runs: list[tuple[int, int]] = []
    run_start = previous = min(protected)
    for boundary in sorted(protected)[1:]:
        if boundary != previous + 1:
            runs.append((run_start, previous))
            run_start = boundary
        previous = boundary
    runs.append((run_start, previous))

    demoted: set[int] = set()
    for first_boundary, last_boundary in runs:
        first_word = first_boundary - 1
        final_word_exclusive = last_boundary + 1
        if _source_span_length(exact_text, words, first_word, final_word_exclusive) <= 45:
            continue
        # state[end] = (damage, cut_count, chosen_cut_positions)
        states: dict[int, tuple[int, int, tuple[int, ...]]] = {
            first_word: (0, 0, ())
        }
        for start in range(first_word, final_word_exclusive):
            current = states.get(start)
            if current is None:
                continue
            for end in range(start + 1, final_word_exclusive + 1):
                if _source_span_length(exact_text, words, start, end) > 45:
                    break
                is_final = end == final_word_exclusive
                boundary_damage = 0 if is_final else _boundary_damage(end, categories)
                candidate = (
                    current[0] + boundary_damage,
                    current[1] + (0 if is_final else 1),
                    current[2] + (() if is_final else (end,)),
                )
                previous_state = states.get(end)
                if previous_state is None or candidate < previous_state:
                    states[end] = candidate
        result = states.get(final_word_exclusive)
        if result is None:
            # A single overlong token cannot be repaired by boundary choice;
            # keep normal validation responsible for the clear hard-limit error.
            continue
        demoted.update(result[2])

    for boundary in demoted:
        for values in categories.values():
            values.discard(boundary)
    return frozenset(demoted)


def _source_span_length(
    exact_text: str,
    words: Sequence[object],
    start: int,
    end: int,
) -> int:
    char_start = int(getattr(words[start], "char_start"))
    char_end = int(getattr(words[end - 1], "char_end"))
    return len(exact_text[char_start:char_end].strip())


def _boundary_damage(boundary: int, categories: dict[str, set[int]]) -> int:
    relevant = [
        _PROTECTION_DAMAGE.get(name, 90)
        for name, positions in categories.items()
        if boundary in positions
    ]
    return sum(relevant) if relevant else 1


def _fallback_analysis(exact_text: str, words: Sequence[object]) -> SyntaxAnalysis:
    count = len(words)
    categories = {name: set() for name in (
        "auxiliary_verb", "verb_particle", "verb_object", "preposition_object",
        "adjective_noun", "compound_noun", "degree_modifier", "temporal_connector",
        "number_unit", "proper_name", "determiner_noun", "subordinator_clause",
        "or_not", "wh_clause",
    )}
    features: list[SyntaxTokenFeature] = []
    keys = [str(getattr(word, "exact_text")).casefold().strip(".,!?;:\"'()[]{}") for word in words]
    for position in range(1, count):
        left, right = keys[position - 1], keys[position]
        if left in _AUXILIARIES or left in {"not", "n't"}:
            categories["auxiliary_verb"].add(position)
        if left in _DETERMINERS:
            categories["determiner_noun"].add(position)
        if left in _PREPOSITIONS:
            categories["preposition_object"].add(position)
        if left in _DEGREE_MODIFIERS:
            categories["degree_modifier"].add(position)
        if left in _TEMPORAL_MODIFIERS and right in {"after", "before", "than", "when"}:
            categories["temporal_connector"].add(position)
        if _looks_numeric(left) and right in _NUMBER_UNITS:
            categories["number_unit"].add(position)
        if right in _OBJECT_PRONOUNS and (_looks_verb(left) or left in _PREPOSITIONS):
            categories["verb_object" if _looks_verb(left) else "preposition_object"].add(position)
        if left in _SUBORDINATORS:
            categories["subordinator_clause"].add(position)
        if left in _WH_COMPLEMENTS:
            categories["wh_clause"].add(position)
        if left == "or" and right == "not":
            categories["or_not"].add(position)
            if position > 1:
                categories["or_not"].add(position - 1)
        if left in _PARTICLES and position >= 2 and _looks_verb(keys[position - 2]):
            categories["verb_particle"].add(position - 1)
        if _looks_modifier(left) and right not in _PREPOSITIONS | _SUBORDINATORS:
            categories["adjective_noun"].add(position)
        left_exact = str(getattr(words[position - 1], "exact_text"))
        right_exact = str(getattr(words[position], "exact_text"))
        if left_exact[:1].isupper() and right_exact[:1].isupper():
            categories["proper_name"].add(position)
    sentence = {
        position for position in range(1, count)
        if any(mark in exact_text[int(getattr(words[position - 1], "char_end")):int(getattr(words[position], "char_start"))] for mark in ".?!…\n\r")
    }
    clause = {position for position in range(1, count) if keys[position] in _SUBORDINATORS}
    protected = set().union(*categories.values()) - sentence
    all_boundaries = set(range(1, count))
    discouraged = set()
    for position in all_boundaries - protected:
        if keys[position - 1] in _PREPOSITIONS | _AUXILIARIES | _DETERMINERS | _DEGREE_MODIFIERS:
            discouraged.add(position)
    for index, word in enumerate(words):
        key = keys[index]
        pos = _fallback_tag(key)
        features.append(SyntaxTokenFeature(
            word_index=index, original_text=str(getattr(word, "exact_text")), display_text=str(getattr(word, "exact_text")),
            lemma=key, char_start=int(getattr(word, "char_start")), char_end=int(getattr(word, "char_end")),
            source_token_index=int(getattr(word, "token_index", index)), timing_reference=int(getattr(word, "script_word_index", index)),
            punctuation_type=_punctuation_after(exact_text, int(getattr(word, "char_end"))), part_of_speech=pos,
            fine_grained_tag="", dependency_relation="fallback", syntactic_head_index=None, sentence_index=0,
            clause_membership=0, is_function_word=pos in _FUNCTION_POS, is_particle=key in _PARTICLES,
            is_degree_modifier=key in _DEGREE_MODIFIERS, is_coordinated_list_member=False,
            protected_span_ids=tuple(name for name, positions in categories.items() if index in positions or index + 1 in positions),
            parser_token_indices=(),
        ))
    return SyntaxAnalysis(
        mode=SyntaxAnalyzerMode.DETERMINISTIC_FALLBACK, model_name="deterministic-fallback-v1", model_version="1",
        parser_initialization_nanoseconds=0, parse_nanoseconds=0, features=tuple(features),
        sentence_boundaries=frozenset(sentence), clause_boundaries=frozenset(clause), list_item_boundaries=frozenset(),
        protected_by_category=tuple((name, frozenset(values)) for name, values in sorted(categories.items())),
        legal_boundaries=frozenset(all_boundaries - protected - discouraged), discouraged_boundaries=frozenset(disccouraged for disccouraged in discouraged),
        forbidden_boundaries=frozenset(protected),
    )


def _primary_token(tokens: Sequence[Any], token_to_word: dict[int, int], word_index: int) -> Any | None:
    if not tokens:
        return None
    for token in tokens:
        if token_to_word.get(int(token.head.i)) != word_index:
            return token
    return tokens[-1]


def _requires_continuation(token: Any) -> bool:
    return token.pos_ in {"ADP", "AUX", "CCONJ", "DET", "PART", "SCONJ"} or token.dep_.lower() in {"aux", "auxpass", "det", "mark", "neg", "poss", "prep", "prt"}


def _is_stranded_beginning(token: Any) -> bool:
    return token.pos_ == "ADP" or token.dep_.lower() in {"dobj", "iobj", "obj", "pobj", "prt", "quantmod"}


def _spacy_list_boundaries(
    document: Any,
    token_to_word: dict[int, int],
    exact_text: str,
    words: Sequence[object],
    word_to_tokens: Sequence[Sequence[Any]],
) -> set[int]:
    boundaries: set[int] = set()
    # A comma run is a list only when it contains at least three short,
    # parallel phrases.  Boundaries use the *start of each complete item*,
    # rather than a dependency head, so modifiers and prepositions stay with
    # their objects.
    comma_positions = [
        position
        for position in range(1, len(words))
        if "," in exact_text[
            int(getattr(words[position - 1], "char_end")):
            int(getattr(words[position], "char_start"))
        ]
    ]
    if len(comma_positions) < 2:
        # Fall through to conj-dependency detection for "X, Y and Z" and
        # "X and Y and Z" patterns that lack two explicit commas.
        return _conj_list_boundaries(document, token_to_word, words, word_to_tokens)

    keys = [
        str(getattr(word, "exact_text")).casefold().strip(".,!?;:\"'()[]{}")
        for word in words
    ]
    # A compact generic list introducer starts a trailing enumeration. Earlier
    # clause commas are not part of that list.
    for marker in range(len(words) - 1, -1, -1):
        if keys[marker] not in _LIST_INTRODUCERS:
            continue
        suffix_commas = [
            position for position in comma_positions if position > marker
        ]
        first_item = marker + 1
        if len(suffix_commas) < 2:
            continue
        edges = (first_item, *suffix_commas, len(words))
        if all(
            1 <= end - start <= 8
            for start, end in zip(edges, edges[1:])
        ):
            if first_item > 0:
                boundaries.add(first_item)
            boundaries.update(suffix_commas)
            return boundaries

    later_ranges = list(
        zip(comma_positions, (*comma_positions[1:], len(words)))
    )
    if any(end - start > 8 or start >= end for start, end in later_ranges):
        return boundaries

    def probe(start: int, end: int) -> int:
        value = str(getattr(words[start], "exact_text")).casefold()
        if value in {"and", "or"} and start + 1 < end:
            return start + 1
        return start

    later_probes = [probe(start, end) for start, end in later_ranges]
    probe_keys = [
        str(getattr(words[index], "exact_text")).casefold()
        for index in later_probes
    ]
    probe_pos = [
        word_to_tokens[index][0].pos_ if word_to_tokens[index] else ""
        for index in later_probes
    ]

    first_end = comma_positions[0]
    first_start: int | None = None
    if probe_keys and len(set(probe_keys)) == 1:
        for index in range(first_end - 1, -1, -1):
            key = str(getattr(words[index], "exact_text")).casefold()
            if key == probe_keys[0]:
                first_start = index
                break
    if first_start is None and probe_pos and len(set(probe_pos)) == 1:
        target_pos = probe_pos[0]
        for index in range(first_end - 1, -1, -1):
            tokens = word_to_tokens[index]
            if tokens and tokens[0].pos_ == target_pos:
                first_start = index
                break

    # For noun/adjective item starts, compare the rightmost phrase heads.
    def phrase_head_position(start: int, end: int) -> str:
        for index in range(end - 1, start - 1, -1):
            tokens = word_to_tokens[index]
            if tokens and tokens[-1].pos_ in {"NOUN", "PROPN", "VERB", "ADJ"}:
                return tokens[-1].pos_
        return ""

    later_heads = [
        phrase_head_position(start, end) for start, end in later_ranges
    ]
    head_candidates = [value for value in later_heads if value]
    dominant_head = (
        max(
            sorted(set(head_candidates)),
            key=head_candidates.count,
        )
        if head_candidates
        else ""
    )
    if first_start is None and dominant_head:
        target = dominant_head
        for index in range(first_end - 1, -1, -1):
            tokens = word_to_tokens[index]
            if tokens and tokens[-1].pos_ == target:
                first_start = index
                break

    # A one- or two-word prefix followed by at least three parallel comma
    # spans is itself the first item, not an introductory clause.
    if first_start is None and first_end <= 2:
        first_start = 0

    if first_start is None:
        return boundaries
    # Include a compact preposition/determiner/modifier immediately attached
    # to the first item head. This mirrors the later comma-delimited spans.
    while first_start > 0:
        tokens = word_to_tokens[first_start - 1]
        if not tokens or tokens[-1].pos_ not in {"ADP", "ADJ", "DET"}:
            break
        first_start -= 1

    item_starts = (first_start, *comma_positions)
    item_ends = (*comma_positions, len(words))
    if any(end - start > 8 or start >= end for start, end in zip(item_starts, item_ends)):
        return boundaries
    if first_start > 0:
        boundaries.add(first_start)
    boundaries.update(comma_positions)
    # Also check conj-based detection; prefer whichever finds more items.
    conj_boundaries = _conj_list_boundaries(document, token_to_word, words, word_to_tokens)
    if len(conj_boundaries) > len(boundaries):
        return conj_boundaries
    return boundaries


def _conj_list_boundaries(
    document: Any,
    token_to_word: dict[int, int],
    words: Sequence[object],
    word_to_tokens: Sequence[Sequence[Any]],
) -> set[int]:
    """Detect enumeration items through spaCy's conj-dependency graph.

    Handles patterns the comma-based path misses:
    - ``X, Y and Z``  (one comma + coordinating conjunction)
    - ``X and Y and Z``  (no commas, chained conj)
    - Repeated-preposition lists: ``at A, at B and at C``

    Rules:
    - At least 3 items total must be present.
    - Every item span must be 1-8 words.
    - A leading ADP/DET immediately preceding the item head is included.
    """
    count = len(words)
    if count < 3:
        return set()

    # Collect direct conj relationships and build child->head mapping.
    conj_direct: dict[int, set[int]] = {}
    child_to_head: dict[int, int] = {}
    for token in document:
        if token.dep_.lower() != "conj":
            continue
        child_wi = token_to_word.get(int(token.i))
        head_wi = token_to_word.get(int(token.head.i))
        if child_wi is None or head_wi is None or child_wi == head_wi:
            continue
        conj_direct.setdefault(head_wi, set()).add(child_wi)
        child_to_head[child_wi] = head_wi

    if not conj_direct:
        return set()

    # Flatten chained conj: in "cats and dogs and birds", spaCy gives
    # dogs->cats, birds->dogs. Transitively resolve so all items share
    # the same root (cats).
    def chain_root(wi: int) -> int:
        seen: set[int] = set()
        while wi in child_to_head and wi not in seen:
            seen.add(wi)
            wi = child_to_head[wi]
        return wi

    # Group all chain members under their ultimate root.
    flat_groups: dict[int, set[int]] = {}
    for child_wi in child_to_head:
        root = chain_root(child_wi)
        flat_groups.setdefault(root, set()).add(child_wi)

    # Also collect parallel prep siblings of the same governing head.
    # In "She pointed at anger, at grief and at fear":
    #   at[2] dep=prep head=pointed[1]
    #   at[4] dep=prep head=pointed[1]  (parallel, not via conj)
    #   at[7] dep=conj head=at[4]
    # at[2] is a prep sibling of the group root at[4].
    for root_wi in list(flat_groups.keys()):
        root_tokens = word_to_tokens[root_wi] if root_wi < len(word_to_tokens) else []
        if not root_tokens:
            continue
        root_tok = root_tokens[0]
        if root_tok.dep_.lower() not in {"prep", "agent"}:
            continue
        gov_wi = token_to_word.get(int(root_tok.head.i))
        if gov_wi is None:
            continue
        for token in document:
            if token.dep_.lower() not in {"prep", "agent"}:
                continue
            if token_to_word.get(int(token.head.i)) != gov_wi:
                continue
            sibling_wi = token_to_word.get(int(token.i))
            if sibling_wi is not None and sibling_wi != root_wi:
                flat_groups[root_wi].add(sibling_wi)

    # Compute the effective start of each item, pulling in any leading
    # ADP (preposition) or DET (determiner) that belongs to the item phrase.
    def _item_start(wi: int) -> int:
        start = wi
        while start > 0:
            prev_tokens = word_to_tokens[start - 1]
            if not prev_tokens:
                break
            prev_pos = prev_tokens[-1].pos_
            prev_dep = prev_tokens[-1].dep_.lower()
            # cc ("and"/"or") belongs to this item, not the previous one.
            # Including it here means the cue reads "and at fear" rather
            # than stranding the cc in the prior cue as "at grief and".
            if prev_dep == "cc":
                start -= 1
                break
            # ADP and DET attach directly to the item head.
            if prev_pos in {"ADP", "DET"}:
                start -= 1
            else:
                break
        return start

    best: set[int] = set()
    for root_wi, conjunct_set in flat_groups.items():
        all_wis = sorted({root_wi} | conjunct_set)
        if len(all_wis) < 3:
            continue

        item_starts = sorted(set(_item_start(wi) for wi in all_wis))
        if len(item_starts) < 3:
            continue

        item_spans = list(zip(item_starts, (*item_starts[1:], count)))
        # Each item must be 1-8 words.
        if any(end - start < 1 or end - start > 8 for start, end in item_spans):
            continue

        candidate: set[int] = set()
        first = item_starts[0]
        if first > 0:
            candidate.add(first)
        for start in item_starts[1:]:
            candidate.add(start)

        if len(candidate) > len(best):
            best = candidate

    return best


def _list_member_words(document: Any, token_to_word: dict[int, int]) -> set[int]:
    result: set[int] = set()
    for token in document:
        if token.dep_.lower() == "conj" and int(token.i) in token_to_word:
            result.add(token_to_word[int(token.i)])
            if int(token.head.i) in token_to_word:
                result.add(token_to_word[int(token.head.i)])
    return result


def _punctuation_after(text: str, end: int) -> str | None:
    if end >= len(text):
        return None
    character = text[end]
    return character if character in ",.;:?!…" else None


def _looks_numeric(value: str) -> bool:
    return any(character.isdigit() for character in value) or value in {"one", "two", "three", "first", "second", "third", "hundred", "hundreds"}


def _looks_verb(value: str) -> bool:
    return value.endswith(("ed", "en", "ing", "ize", "ise", "s")) or value in {"be", "break", "carry", "get", "give", "help", "look", "move", "protect", "shut", "turn", "wear", "work", "wrap"}


def _looks_modifier(value: str) -> bool:
    return value.endswith(("al", "ary", "ed", "ful", "ic", "ive", "less", "ous"))


def _fallback_tag(value: str) -> str:
    if value in _AUXILIARIES:
        return "AUX"
    if value in _DETERMINERS:
        return "DET"
    if value in _PREPOSITIONS:
        return "ADP"
    if value in _SUBORDINATORS:
        return "SCONJ"
    if value in _DEGREE_MODIFIERS or value.endswith("ly"):
        return "ADV"
    if _looks_verb(value):
        return "VERB"
    return "NOUN"
