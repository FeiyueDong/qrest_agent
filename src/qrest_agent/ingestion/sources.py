from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SourceChunk:
    source_id: str
    location: str
    text: str
    source_type: str = "text"

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "location": self.location,
            "text": self.text,
            "source_type": self.source_type,
        }


class SourceManager:
    def __init__(self) -> None:
        self._chunks: list[SourceChunk] = []

    @property
    def chunks(self) -> list[SourceChunk]:
        return list(self._chunks)

    def add_text(self, text: str, source_id: str = "user_message", source_type: str = "chat") -> list[SourceChunk]:
        chunks = _chunk_text(text)
        created = [
            SourceChunk(source_id=source_id, location=f"chunk:{index + 1}", text=chunk, source_type=source_type)
            for index, chunk in enumerate(chunks)
        ]
        self._chunks.extend(created)
        return created

    def add_file(self, path: str | Path, source_id: str | None = None) -> list[SourceChunk]:
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        source_id = source_id or file_path.name

        if suffix == ".json":
            text = file_path.read_text(encoding="utf-8")
            chunk = SourceChunk(source_id=source_id, location="document", text=text, source_type="json")
            self._chunks.append(chunk)
            return [chunk]

        if suffix in {".txt", ".md", ".yml", ".yaml", ".csv"}:
            text = file_path.read_text(encoding="utf-8")
            return self.add_text(text, source_id=source_id, source_type=suffix.removeprefix("."))

        if suffix in {".pdf", ".docx", ".xlsx"}:
            raise NotImplementedError(
                f"{suffix} ingestion is reserved for the document parser layer. "
                "Install the docs extra and implement a parser before enabling it."
            )

        text = file_path.read_text(encoding="utf-8")
        return self.add_text(text, source_id=source_id, source_type="text")

    def search(self, query: str, limit: int = 5) -> list[SourceChunk]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return self.chunks[:limit]

        scored: list[tuple[int, SourceChunk]] = []
        for chunk in self._chunks:
            text = chunk.text.lower()
            score = sum(text.count(term) for term in terms)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]


def _chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        if len(current) + len(paragraph) + 1 <= max_chars:
            current = f"{current}\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)
    return chunks
