from __future__ import annotations

import csv
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

        if suffix in {".txt", ".md", ".yml", ".yaml"}:
            text = file_path.read_text(encoding="utf-8")
            return self.add_text(text, source_id=source_id, source_type=suffix.removeprefix("."))

        if suffix == ".csv":
            return self._add_csv(file_path, source_id)

        if suffix == ".pdf":
            return self._add_pdf(file_path, source_id)

        if suffix == ".docx":
            return self._add_docx(file_path, source_id)

        if suffix == ".xlsx":
            return self._add_xlsx(file_path, source_id)

        text = file_path.read_text(encoding="utf-8")
        return self.add_text(text, source_id=source_id, source_type="text")

    def _add_pdf(self, file_path: Path, source_id: str) -> list[SourceChunk]:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(file_path), "-"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"pdftotext failed for {file_path}: {completed.stderr}")
        pages = completed.stdout.split("\f")
        created: list[SourceChunk] = []
        for page_index, page_text in enumerate(pages, start=1):
            for chunk_index, text in enumerate(_chunk_text(page_text), start=1):
                created.append(
                    SourceChunk(
                        source_id=source_id,
                        location=f"page:{page_index}/chunk:{chunk_index}",
                        text=text,
                        source_type="pdf",
                    )
                )
        self._chunks.extend(created)
        return created

    def _add_docx(self, file_path: Path, source_id: str) -> list[SourceChunk]:
        paragraphs = _read_docx_paragraphs(file_path)
        created = [
            SourceChunk(
                source_id=source_id,
                location=f"paragraph:{index}",
                text=paragraph,
                source_type="docx",
            )
            for index, paragraph in enumerate(paragraphs, start=1)
            if paragraph.strip()
        ]
        self._chunks.extend(created)
        return created

    def _add_csv(self, file_path: Path, source_id: str) -> list[SourceChunk]:
        rows: list[str] = []
        with file_path.open("r", encoding="utf-8", newline="") as handle:
            for row_index, row in enumerate(csv.reader(handle), start=1):
                rows.append(f"row {row_index}: " + "\t".join(row))
        text = "\n".join(rows)
        chunks = _chunk_text(text)
        created = [
            SourceChunk(source_id=source_id, location=f"rows/chunk:{index}", text=chunk, source_type="csv")
            for index, chunk in enumerate(chunks, start=1)
        ]
        self._chunks.extend(created)
        return created

    def _add_xlsx(self, file_path: Path, source_id: str) -> list[SourceChunk]:
        sheets = _read_xlsx_sheets(file_path)
        created: list[SourceChunk] = []
        for sheet_name, rows in sheets.items():
            text = "\n".join(rows)
            for chunk_index, chunk in enumerate(_chunk_text(text), start=1):
                created.append(
                    SourceChunk(
                        source_id=source_id,
                        location=f"sheet:{sheet_name}/chunk:{chunk_index}",
                        text=chunk,
                        source_type="xlsx",
                    )
                )
        self._chunks.extend(created)
        return created

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


def _read_docx_paragraphs(path: Path) -> list[str]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns)).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _read_xlsx_sheets(path: Path) -> dict[str, list[str]]:
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings = _read_xlsx_shared_strings(archive)
        sheet_files = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        sheets: dict[str, list[str]] = {}
        for sheet_index, sheet_file in enumerate(sheet_files, start=1):
            root = ET.fromstring(archive.read(sheet_file))
            rows: list[str] = []
            for row in root.findall(".//main:row", ns):
                row_values = [_xlsx_cell_value(cell, shared_strings, ns) for cell in row.findall("main:c", ns)]
                rows.append("\t".join(row_values))
            sheets[f"sheet{sheet_index}"] = rows
    return sheets


def _read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(".//main:si", ns):
        values.append("".join(node.text or "" for node in item.findall(".//main:t", ns)))
    return values


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("main:v", ns)
    if value_node is None or value_node.text is None:
        return ""
    if cell_type == "s":
        index = int(value_node.text)
        return shared_strings[index] if index < len(shared_strings) else ""
    return value_node.text
