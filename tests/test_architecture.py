"""Lightweight dependency-boundary and cycle checks for the scaffold."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "larp_audio_mvp"
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE
FORBIDDEN_EXTERNAL_PREFIXES = {
    "anthropic",
    "boto3",
    "celery",
    "chromadb",
    "django",
    "google.generativeai",
    "librosa",
    "numpy",
    "openai",
    "pydub",
    "redis",
    "requests",
    "scipy",
    "soundfile",
    "torch",
    "whisper",
}
FORBIDDEN_CORE_LAYERS = {
    "alignment",
    "app",
    "audio",
    "config",
    "exports",
    "models",
    "pipeline",
    "subtitles",
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join((PACKAGE, *parts)) if parts else PACKAGE


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _closest_project_module(imported: str, modules: set[str]) -> str | None:
    candidate = imported
    while candidate.startswith(PACKAGE):
        if candidate in modules:
            return candidate
        if "." not in candidate:
            break
        candidate = candidate.rsplit(".", 1)[0]
    return None


def test_forbidden_dependencies_are_absent() -> None:
    for path in SOURCE_ROOT.rglob("*.py"):
        imports = _imports(path)
        for imported in imports:
            assert not any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_EXTERNAL_PREFIXES
            ), f"forbidden dependency {imported!r} in {path}"


def test_pyside6_is_confined_to_gui_presentation_layer() -> None:
    for path in SOURCE_ROOT.rglob("*.py"):
        imports_qt = any(
            imported == "PySide6" or imported.startswith("PySide6.")
            for imported in _imports(path)
        )
        if imports_qt:
            relative = path.relative_to(SOURCE_ROOT)
            assert relative.parts[0] == "gui", (
                f"PySide6 import escaped GUI layer: {path}"
            )


def test_core_does_not_depend_on_outer_layers() -> None:
    for path in (SOURCE_ROOT / "core").rglob("*.py"):
        for imported in _imports(path):
            parts = imported.split(".")
            if len(parts) >= 2 and parts[0] == PACKAGE:
                assert parts[1] not in FORBIDDEN_CORE_LAYERS, (
                    f"core imports outer layer {imported!r} in {path}"
                )


def test_project_import_graph_has_no_cycles() -> None:
    paths = tuple(SOURCE_ROOT.rglob("*.py"))
    path_by_module = {_module_name(path): path for path in paths}
    modules = set(path_by_module)
    graph = {
        module: {
            dependency
            for imported in _imports(path)
            if (dependency := _closest_project_module(imported, modules))
            and dependency != module
        }
        for module, path in path_by_module.items()
    }

    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            cycle = " -> ".join((*active[active.index(module) :], module))
            raise AssertionError(f"cyclic project dependency: {cycle}")
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
