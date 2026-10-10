"""Validate raw data folders: data/raw/{SYMBOL}/FY{FY}/.

Checks that the expected files exist, the annual report PDF opens and has pages, and both XBRL
files are well-formed XBRL. Works the same for scripted and manual downloads.

Usage:
    python -m annualyst.ingest.validate                    # all COMPANIES x FISCAL_YEARS
    python -m annualyst.ingest.validate --symbol TCS --fy 2025
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from annualyst.ingest.download import (
    AR_PDF,
    COMPANIES,
    FISCAL_YEARS,
    MANIFEST,
    RAW_ROOT,
    XBRL_FILES,
    parse_fy,
)

XBRL_NS = "{http://www.xbrl.org/2003/instance}"


@dataclass
class FolderReport:
    symbol: str
    fy: int
    pages: int | None = None
    xbrl_ok: dict[str, bool] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _pdf_page_count(path: Path) -> tuple[int | None, str | None]:
    # PyMuPDF also opens HTML/text as documents, so an "Access Denied" page saved as .pdf
    # would pass without this magic-byte check.
    with path.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            return None, f"{path.name} does not open as a PDF: missing %PDF- header"
    try:
        with pymupdf.open(path, filetype="pdf") as doc:
            if doc.needs_pass:
                return None, f"{path.name} is password-protected"
            if doc.page_count == 0:
                return None, f"{path.name} has 0 pages"
            return doc.page_count, None
    except Exception as exc:  # PyMuPDF raises several exception types for corrupt files
        return None, f"{path.name} does not open as a PDF: {exc}"


def _xbrl_problem(path: Path) -> str | None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return f"{path.name} is not well-formed XML: {exc}"
    if root.tag != f"{XBRL_NS}xbrl":
        return f"{path.name} is XML but not an XBRL instance (root <{root.tag}>)"
    return None


def validate_company_year(folder: Path, symbol: str, fy: int) -> FolderReport:
    report = FolderReport(symbol, fy)
    if not folder.is_dir():
        report.problems.append(f"folder {folder} does not exist")
        return report

    pdf = folder / AR_PDF
    if pdf.exists():
        report.pages, problem = _pdf_page_count(pdf)
        if problem:
            report.problems.append(problem)
    else:
        report.problems.append(f"{AR_PDF} missing")

    for name in XBRL_FILES.values():
        path = folder / name
        if not path.exists():
            report.problems.append(f"{name} missing")
            report.xbrl_ok[name] = False
            continue
        problem = _xbrl_problem(path)
        report.xbrl_ok[name] = problem is None
        if problem:
            report.problems.append(problem)

    manifest = folder / MANIFEST
    if manifest.exists():
        report.warnings += json.loads(manifest.read_text(encoding="utf-8")).get("warnings", [])
    else:
        report.warnings.append(f"no {MANIFEST} (manual download?): source URLs not recorded")
    return report


def validate_all(
    root: Path = RAW_ROOT,
    symbols: list[str] | None = None,
    years: list[int] | None = None,
) -> list[FolderReport]:
    return [
        validate_company_year(root / symbol / f"FY{fy}", symbol, fy)
        for symbol in symbols or COMPANIES
        for fy in years or FISCAL_YEARS
    ]


def format_table(reports: list[FolderReport]) -> str:
    cons, std = XBRL_FILES[True], XBRL_FILES[False]
    lines = [f"{'symbol':<12}{'FY':<8}{'pages':>6}  {'cons':<6}{'stand':<6}status"]
    for r in reports:
        pages = str(r.pages) if r.pages is not None else "-"
        mark = {True: "ok", False: "BAD"}
        lines.append(
            f"{r.symbol:<12}{'FY' + str(r.fy):<8}{pages:>6}  "
            f"{mark[r.xbrl_ok.get(cons, False)]:<6}{mark[r.xbrl_ok.get(std, False)]:<6}"
            f"{'ok' if r.ok else 'PROBLEM'}"
        )
        lines += [f"    problem: {p}" for p in r.problems]
        lines += [f"    warning: {w}" for w in r.warnings]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--symbol", help="NSE symbol, e.g. TCS (default: all v1 companies)")
    parser.add_argument(
        "--fy", type=parse_fy, help="fiscal year, e.g. 2025 (default: FY2023-FY2025)"
    )
    parser.add_argument("--root", type=Path, default=RAW_ROOT)
    args = parser.parse_args(argv)

    reports = validate_all(
        args.root,
        [args.symbol.upper()] if args.symbol else None,
        [args.fy] if args.fy else None,
    )
    print(format_table(reports))
    bad = sum(not r.ok for r in reports)
    print(f"\n{len(reports) - bad}/{len(reports)} folders valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
