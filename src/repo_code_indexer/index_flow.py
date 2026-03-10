from __future__ import annotations

import ast
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sentence_transformers import SentenceTransformer

from repo_code_indexer.projects import IGNORED_DIRS


SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".m",
    ".mm",
    ".swift",
    ".scala",
    ".lua",
    ".sh",
    ".zsh",
    ".bash",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".xml",
}

CHUNK_SPLIT_HINTS = (
    "\nclass ",
    "\ndef ",
    "\nasync def ",
    "\nfunction ",
    "\nexport ",
    "\nconst ",
    "\nlet ",
    "\nvar ",
    "\n\n",
)


@dataclass(frozen=True)
class CodeChunk:
    project_name: str
    file_path: str
    chunk_index: int
    language: str
    content: str
    search_text: str
    path_tokens: str
    symbol_name: str | None
    symbol_type: str | None
    start_line: int
    end_line: int


@dataclass(frozen=True)
class SymbolSpan:
    name: str
    symbol_type: str
    start_line: int
    end_line: int
    text: str


def detect_language(path: Path) -> str:
    ext = path.suffix.lower()
    if ext.startswith("."):
        return ext[1:] or "text"
    return "text"


def iter_files(project_dir: Path) -> Iterable[Path]:
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue

        if any(part in IGNORED_DIRS for part in path.parts):
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        yield path


def read_text_file(path: Path) -> str | None:
    encodings = ("utf-8", "utf-8-sig", "latin-1")
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    return None


def _split_identifier(value: str) -> list[str]:
    parts = re.split(r"[^A-Za-z0-9]+", value)
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", part)
        if camel_parts:
            tokens.extend(piece.lower() for piece in camel_parts if piece)
        else:
            tokens.append(part.lower())
    return tokens


def extract_path_tokens(file_path: str) -> str:
    values: list[str] = []
    for part in Path(file_path).parts:
        values.extend(_split_identifier(part))

    seen: set[str] = set()
    unique_tokens: list[str] = []
    for token in values:
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)
    return " ".join(unique_tokens)


def _line_offsets(content: str) -> list[int]:
    offsets = [0]
    for match in re.finditer(r"\n", content):
        offsets.append(match.end())
    return offsets


def _line_for_offset(offsets: list[int], target: int) -> int:
    line = 1
    for idx, offset in enumerate(offsets, start=1):
        if offset > target:
            break
        line = idx
    return line


def _slice_to_lines(content: str, start: int, end: int) -> tuple[int, int]:
    offsets = _line_offsets(content)
    start_line = _line_for_offset(offsets, start)
    end_line = _line_for_offset(offsets, max(start, end - 1))
    return start_line, end_line


def chunk_text_with_lines(
    content: str,
    max_chars: int = 1600,
    overlap: int = 200,
    base_line: int = 1,
) -> list[tuple[str, int, int]]:
    content = content.strip()
    if not content:
        return []

    if len(content) <= max_chars:
        line_count = content.count("\n")
        return [(content, base_line, base_line + line_count)]

    offsets = _line_offsets(content)
    chunks: list[tuple[str, int, int]] = []
    start = 0
    length = len(content)

    while start < length:
        end = min(start + max_chars, length)
        chunk = content[start:end]

        if end < length:
            split_at = max(chunk.rfind(marker) for marker in CHUNK_SPLIT_HINTS)
            if split_at > 200:
                end = start + split_at
                chunk = content[start:end]

        clean_chunk = chunk.strip()
        if clean_chunk:
            start_line, end_line = _slice_to_lines(content, start, end)
            chunks.append(
                (clean_chunk, base_line + start_line - 1, base_line + end_line - 1)
            )

        if end >= length:
            break
        start = max(end - overlap, start + 1)

    return chunks


class _PythonSymbolCollector(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source = source
        self.class_stack: list[str] = []
        self.spans: list[SymbolSpan] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._append_span(node, node.name, "class")
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._append_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._append_function(node)
        self.generic_visit(node)

    def _append_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.class_stack:
            symbol_name = ".".join([*self.class_stack, node.name])
            symbol_type = "method"
        else:
            symbol_name = node.name
            symbol_type = "function"
        self._append_span(node, symbol_name, symbol_type)

    def _append_span(
        self,
        node: ast.AST,
        symbol_name: str,
        symbol_type: str,
    ) -> None:
        start_line = getattr(node, "lineno", None)
        end_line = getattr(node, "end_lineno", None)
        if start_line is None or end_line is None:
            return

        segment = ast.get_source_segment(self.source, node)
        if not segment:
            return

        self.spans.append(
            SymbolSpan(
                name=symbol_name,
                symbol_type=symbol_type,
                start_line=start_line,
                end_line=end_line,
                text=segment.strip(),
            )
        )


def extract_python_symbol_spans(content: str) -> list[SymbolSpan]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    collector = _PythonSymbolCollector(content)
    collector.visit(tree)
    return collector.spans


def _make_search_text(
    file_path: str,
    language: str,
    path_tokens: str,
    content: str,
    symbol_name: str | None,
    symbol_type: str | None,
) -> str:
    parts = [
        f"file_path: {file_path}",
        f"language: {language}",
    ]
    if symbol_name:
        parts.append(f"symbol_name: {symbol_name}")
    if symbol_type:
        parts.append(f"symbol_type: {symbol_type}")
    if path_tokens:
        parts.append(f"path_tokens: {path_tokens}")
    parts.append("content:")
    parts.append(content.strip())
    return "\n".join(part for part in parts if part)


def _module_level_ranges(
    total_lines: int, spans: list[SymbolSpan]
) -> list[tuple[int, int]]:
    if not spans:
        return [(1, total_lines)] if total_lines > 0 else []

    ranges: list[tuple[int, int]] = []
    cursor = 1
    for span in sorted(spans, key=lambda item: (item.start_line, item.end_line)):
        if span.start_line > cursor:
            ranges.append((cursor, span.start_line - 1))
        cursor = max(cursor, span.end_line + 1)
    if cursor <= total_lines:
        ranges.append((cursor, total_lines))
    return [(start, end) for start, end in ranges if start <= end]


def _extract_lines(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines()
    return "\n".join(lines[start_line - 1 : end_line]).strip()


def _structured_file_chunks(
    project_name: str,
    file_path: str,
    language: str,
    content: str,
    max_chars: int,
    overlap: int,
) -> list[CodeChunk]:
    path_tokens = extract_path_tokens(file_path)
    chunks: list[CodeChunk] = []
    next_index = 0

    if language == "py":
        spans = extract_python_symbol_spans(content)
        for span in spans:
            for piece, start_line, end_line in chunk_text_with_lines(
                span.text,
                max_chars=max_chars,
                overlap=overlap,
                base_line=span.start_line,
            ):
                chunks.append(
                    CodeChunk(
                        project_name=project_name,
                        file_path=file_path,
                        chunk_index=next_index,
                        language=language,
                        content=piece,
                        search_text=_make_search_text(
                            file_path,
                            language,
                            path_tokens,
                            piece,
                            span.name,
                            span.symbol_type,
                        ),
                        path_tokens=path_tokens,
                        symbol_name=span.name,
                        symbol_type=span.symbol_type,
                        start_line=start_line,
                        end_line=end_line,
                    )
                )
                next_index += 1

        module_ranges = _module_level_ranges(content.count("\n") + 1, spans)
        for start_line, end_line in module_ranges:
            section = _extract_lines(content, start_line, end_line)
            if not section:
                continue
            for piece, piece_start, piece_end in chunk_text_with_lines(
                section,
                max_chars=max_chars,
                overlap=overlap,
                base_line=start_line,
            ):
                chunks.append(
                    CodeChunk(
                        project_name=project_name,
                        file_path=file_path,
                        chunk_index=next_index,
                        language=language,
                        content=piece,
                        search_text=_make_search_text(
                            file_path,
                            language,
                            path_tokens,
                            piece,
                            None,
                            "module",
                        ),
                        path_tokens=path_tokens,
                        symbol_name=None,
                        symbol_type="module",
                        start_line=piece_start,
                        end_line=piece_end,
                    )
                )
                next_index += 1

        if chunks:
            return chunks

    for piece, start_line, end_line in chunk_text_with_lines(
        content,
        max_chars=max_chars,
        overlap=overlap,
    ):
        chunks.append(
            CodeChunk(
                project_name=project_name,
                file_path=file_path,
                chunk_index=next_index,
                language=language,
                content=piece,
                search_text=_make_search_text(
                    file_path,
                    language,
                    path_tokens,
                    piece,
                    None,
                    None,
                ),
                path_tokens=path_tokens,
                symbol_name=None,
                symbol_type=None,
                start_line=start_line,
                end_line=end_line,
            )
        )
        next_index += 1

    return chunks


def build_chunks(
    project_dir: Path,
    max_chars: int = 1600,
    overlap: int = 200,
) -> list[CodeChunk]:
    project_name = project_dir.name
    result: list[CodeChunk] = []

    for file_path in iter_files(project_dir):
        raw = read_text_file(file_path)
        if not raw:
            continue

        rel = file_path.relative_to(project_dir).as_posix()
        language = detect_language(file_path)
        result.extend(
            _structured_file_chunks(
                project_name,
                rel,
                language,
                raw,
                max_chars=max_chars,
                overlap=overlap,
            )
        )

    return result


_MODEL_CACHE: dict[str, SentenceTransformer] = {}
_MODEL_LOCK = threading.Lock()


def _get_model(model_name: str) -> SentenceTransformer:
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(model_name)
        if model is None:
            model = SentenceTransformer(model_name)
            _MODEL_CACHE[model_name] = model
        return model


def embed_texts(model_name: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    model = _get_model(model_name)
    vectors = model.encode(texts, normalize_embeddings=True)
    return [list(map(float, row)) for row in vectors]


def warm_embedding_model(model_name: str) -> None:
    _get_model(model_name)
