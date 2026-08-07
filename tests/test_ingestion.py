from __future__ import annotations

import zipfile
from pathlib import Path

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.ingestion.sources import SourceManager
from tests.conftest import write_json, write_text


INPUT_DOC_ROOT = Path("resources/input_doc")
DOCX_CASE = INPUT_DOC_ROOT / "Kunming_building_metadata_test_case.docx"
PDF_CASE = INPUT_DOC_ROOT / "Kunming_building_metadata_test_case.pdf"


def test_docx_ingestion_creates_paragraph_chunks(artifact_dir: Path) -> None:
    manager = SourceManager()

    chunks = manager.add_file(DOCX_CASE)

    write_json(artifact_dir / "ingestion" / "docx_chunks.json", [chunk.to_dict() for chunk in chunks])
    write_text(artifact_dir / "ingestion" / "docx_text.txt", "\n\n".join(chunk.text for chunk in chunks))

    assert chunks
    assert all(chunk.source_type == "docx" for chunk in chunks)
    assert any("昆明隔震建筑工程信息提取测试案例" in chunk.text for chunk in chunks)
    assert any("采样时间间隔" in chunk.text for chunk in chunks)


def test_pdf_ingestion_creates_page_chunks(artifact_dir: Path) -> None:
    manager = SourceManager()

    chunks = manager.add_file(PDF_CASE)

    write_json(artifact_dir / "ingestion" / "pdf_chunks.json", [chunk.to_dict() for chunk in chunks])
    write_text(artifact_dir / "ingestion" / "pdf_text.txt", "\n\n".join(chunk.text for chunk in chunks))

    assert chunks
    assert all(chunk.source_type == "pdf" for chunk in chunks)
    assert any(chunk.location.startswith("page:1/") for chunk in chunks)
    assert any("昆明隔震建筑工程信息提取测试案例" in chunk.text for chunk in chunks)
    assert any("采样时间间隔" in chunk.text for chunk in chunks)


def test_docx_and_pdf_ingestion_extract_equivalent_key_text(artifact_dir: Path) -> None:
    manager = SourceManager()
    docx_chunks = manager.add_file(DOCX_CASE)
    pdf_chunks = manager.add_file(PDF_CASE)

    docx_text = "\n".join(chunk.text for chunk in docx_chunks)
    pdf_text = "\n".join(chunk.text for chunk in pdf_chunks)
    summary = {
        "docx_chunk_count": len(docx_chunks),
        "pdf_chunk_count": len(pdf_chunks),
        "shared_checks": {
            "event_name": "2025_MYANMAR_7.9" in docx_text and "2025_MYANMAR_7.9" in pdf_text,
            "channel_count": "18" in docx_text and "18" in pdf_text,
            "sampling_dt": "0.02" in docx_text and "0.02" in pdf_text,
        },
    }
    write_json(artifact_dir / "ingestion" / "docx_pdf_equivalence_summary.json", summary)

    assert summary["shared_checks"]["event_name"]
    assert summary["shared_checks"]["channel_count"]
    assert summary["shared_checks"]["sampling_dt"]


def test_agent_extracts_candidates_from_docx_and_pdf(artifact_dir: Path) -> None:
    outputs = {}
    for path in (DOCX_CASE, PDF_CASE):
        agent = MetadataAgent()
        result = agent.run_turn(files=[path])
        candidate_paths = {candidate.field_path for candidate in result.candidates}
        outputs[path.suffix.removeprefix(".")] = result.to_dict()

        assert "DataInfo.EventName" in candidate_paths
        assert "DataInfo.StartTime" in candidate_paths
        assert "DataInfo.DT" in candidate_paths
        assert "DataInfo.NPTS" in candidate_paths
        assert "InstrumentInfo.ChannelNum" in candidate_paths
        assert "InstrumentInfo.Channels" in candidate_paths
        assert "BuildingInfo.StructuralFootprint.Parameters" in candidate_paths
        assert "BuildingInfo.StructuralFootprint.BoundingBox" in candidate_paths
        assert "BuildingInfo.Elevation" in candidate_paths

        by_path = {candidate.field_path: candidate for candidate in result.candidates}
        elevations = by_path["BuildingInfo.Elevation"].value
        channels = by_path["InstrumentInfo.Channels"].value
        channel_heights = sorted({channel["LocationXYZ"][2] for channel in channels})

        assert len(elevations) == 16
        assert elevations[:5] == [-2.6, 0.0, 4.5, 7.8, 11.1]
        assert len(channels) == 18
        assert channel_heights == [-2.6, 0.0, 11.1, 21.0, 30.9, 44.1]
        assert channels[0]["LocationXYZ"] == [-20.6, -4.2, -2.6]
        assert channels[0]["DeviceType"] == "941B"
        assert result.report.ready
        assert "InstrumentInfo.ChannelNum" not in result.report.conflicts
        assert "InstrumentInfo.Channels" not in result.report.missing_required
        assert "BuildingInfo.Elevation" not in result.report.missing_required
        assert "BuildingInfo.ProjectName" in result.report.missing_optional

    write_json(artifact_dir / "ingestion" / "document_agent_extraction_results.json", outputs)


def test_csv_ingestion_creates_row_chunks(tmp_path: Path, artifact_dir: Path) -> None:
    csv_path = tmp_path / "channels.csv"
    csv_path.write_text("ChannelNo,ChannelID\n1,X1\n2,X2\n", encoding="utf-8")
    manager = SourceManager()

    chunks = manager.add_file(csv_path)

    write_json(artifact_dir / "ingestion" / "csv_chunks.json", [chunk.to_dict() for chunk in chunks])

    assert chunks
    assert chunks[0].source_type == "csv"
    assert "row 1" in chunks[0].text
    assert "ChannelNo" in chunks[0].text


def test_xlsx_ingestion_creates_sheet_chunks(tmp_path: Path, artifact_dir: Path) -> None:
    xlsx_path = tmp_path / "channels.xlsx"
    _write_minimal_xlsx(xlsx_path)
    manager = SourceManager()

    chunks = manager.add_file(xlsx_path)

    write_json(artifact_dir / "ingestion" / "xlsx_chunks.json", [chunk.to_dict() for chunk in chunks])

    assert chunks
    assert chunks[0].source_type == "xlsx"
    assert chunks[0].location.startswith("sheet:sheet1/")
    assert "ChannelNo" in chunks[0].text
    assert "X1" in chunks[0].text


def _write_minimal_xlsx(path: Path) -> None:
    sheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>
  </sheetData>
</worksheet>
"""
    shared_strings_xml = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
  <si><t>ChannelNo</t></si>
  <si><t>ChannelID</t></si>
  <si><t>X1</t></si>
</sst>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
