import json
import shutil
from pathlib import Path

import pytest

from annualyst.ingest import validate as v

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def good_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "TCS" / "FY2025"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURES / "tiny.pdf", folder / "annual_report.pdf")
    shutil.copy(FIXTURES / "tiny_xbrl.xml", folder / "results_consolidated.xml")
    shutil.copy(FIXTURES / "tiny_xbrl.xml", folder / "results_standalone.xml")
    (folder / "source.json").write_text(json.dumps({"files": {}, "warnings": []}))
    return folder


def test_good_folder_passes_and_counts_pages(good_folder: Path) -> None:
    report = v.validate_company_year(good_folder, "TCS", 2025)
    assert report.ok, report.problems
    assert report.pages == 2
    assert report.warnings == []


def test_missing_xbrl_is_reported(good_folder: Path) -> None:
    (good_folder / "results_standalone.xml").unlink()
    report = v.validate_company_year(good_folder, "TCS", 2025)
    assert not report.ok
    assert report.problems == ["results_standalone.xml missing"]


def test_corrupt_pdf_is_reported(good_folder: Path) -> None:
    (good_folder / "annual_report.pdf").write_bytes(b"<html>Access Denied</html>")
    report = v.validate_company_year(good_folder, "TCS", 2025)
    assert report.pages is None
    assert any("does not open as a PDF" in p for p in report.problems)


def test_non_xbrl_xml_is_reported(good_folder: Path) -> None:
    (good_folder / "results_consolidated.xml").write_text("<html><body>error</body></html>")
    report = v.validate_company_year(good_folder, "TCS", 2025)
    assert any("not an XBRL instance" in p for p in report.problems)


def test_manifest_warnings_surface_and_missing_manifest_warns(good_folder: Path) -> None:
    (good_folder / "source.json").write_text(json.dumps({"warnings": ["zip has 2 PDFs"]}))
    assert v.validate_company_year(good_folder, "TCS", 2025).warnings == ["zip has 2 PDFs"]
    (good_folder / "source.json").unlink()
    report = v.validate_company_year(good_folder, "TCS", 2025)
    assert report.ok and "manual download" in report.warnings[0]


def test_main_exit_code_reflects_problems(
    good_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = good_folder.parents[1]
    assert v.main(["--root", str(root), "--symbol", "TCS", "--fy", "FY2025"]) == 0
    assert v.main(["--root", str(root), "--symbol", "TCS", "--fy", "2024"]) == 1
    out = capsys.readouterr().out
    assert "folder" in out and "does not exist" in out
