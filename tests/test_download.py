import io
import json
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pytest

from annualyst.ingest import download as dl

FIXTURES = Path(__file__).parent / "fixtures"
NSE = FIXTURES / "nse"
PDF_BYTES = (FIXTURES / "tiny.pdf").read_bytes()
XML_BYTES = (FIXTURES / "tiny_xbrl.xml").read_bytes()


def load(name: str):
    return json.loads((NSE / name).read_text(encoding="utf-8"))


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class FakeNse:
    """MockTransport handler serving the fixture listings and fake files."""

    def __init__(self, zip_bytes: bytes | None = None, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.zip_bytes = zip_bytes or make_zip({"report.pdf": PDF_BYTES})
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status)
        path = request.url.path
        if path == "/api/annual-reports":
            return httpx.Response(200, json=load("annual_reports_tcs.json"))
        if path == "/api/corporates-financial-results":
            return httpx.Response(200, json=load("results_legacy_tcs.json"))
        if path == "/api/integrated-filing-results":
            return httpx.Response(200, json=load("results_integrated_tcs.json"))
        if path.endswith(".pdf"):
            return httpx.Response(200, content=PDF_BYTES)
        if path.endswith(".zip"):
            return httpx.Response(200, content=self.zip_bytes)
        if path.endswith(".xml"):
            return httpx.Response(200, content=XML_BYTES)
        return httpx.Response(404)


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def make_client(fake: FakeNse) -> dl.NseClient:
    t = FakeTime()
    return dl.NseClient(
        http=httpx.Client(transport=httpx.MockTransport(fake)),
        limiter=dl.RateLimiter(clock=t.clock, sleep=t.sleep),
    )


# --- pure selection -----------------------------------------------------------


def test_fy_bounds_follow_indian_fiscal_year() -> None:
    assert dl.fy_bounds(2025) == (date(2024, 4, 1), date(2025, 3, 31))


def test_parse_fy_accepts_prefix() -> None:
    assert dl.parse_fy("FY2024") == dl.parse_fy("2024") == 2024


def test_select_annual_report_by_year() -> None:
    entries = load("annual_reports_tcs.json")["data"]
    sel = dl.select_annual_report(entries, 2025)
    assert sel is not None and sel.url.endswith("AR_26456_TCS_2024_2025_A_27052025233502.pdf")
    assert sel.warnings == []
    assert dl.select_annual_report(entries, 2019) is None


def test_select_xbrl_legacy_consolidated_and_standalone() -> None:
    entries = load("results_legacy_tcs.json")
    cons = dl.select_xbrl(entries, 2024, consolidated=True)
    std = dl.select_xbrl(entries, 2024, consolidated=False)
    assert cons is not None and "INDAS_104549" in cons.url
    assert std is not None and "INDAS_104550" in std.url


def test_select_xbrl_integrated_uses_march_quarter_end() -> None:
    entries = load("results_integrated_tcs.json")["data"]
    cons = dl.select_xbrl(entries, 2025, consolidated=True)
    std = dl.select_xbrl(entries, 2025, consolidated=False)
    assert cons is not None and "1412101" in cons.url
    assert std is not None and "1412100" in std.url


def test_select_xbrl_skips_filings_without_xbrl() -> None:
    assert dl.select_xbrl(load("results_legacy_tcs.json"), 2018, consolidated=True) is None


def test_select_xbrl_duplicate_filings_pick_latest_and_warn() -> None:
    entries = load("results_integrated_tcs.json")["data"]
    revised = dict(entries[2], broadcast_Date="20-Apr-2025 10:00:00", xbrl="https://x/revised.xml")
    sel = dl.select_xbrl([*entries, revised], 2025, consolidated=True)
    assert sel is not None and sel.url == "https://x/revised.xml"
    assert len(sel.warnings) == 1 and entries[2]["xbrl"] in sel.warnings[0]


def test_select_xbrl_prefers_revision_without_broadcast_date() -> None:
    # Real shape from ASIANPAINT FY2025: the revision has broadcast_Date=None.
    original = {
        "type": "Integrated Filing- Financials",
        "qe_Date": "31-MAR-2025",
        "consolidated": "Standalone",
        "type_Sub": "Original",
        "broadcast_Date": "08-May-2025 20:01:42",
        "revised_Date": None,
        "xbrl": "https://x/original.xml",
    }
    revision = dict(
        original,
        type_Sub="Revision",
        broadcast_Date=None,
        creation_Date="14-Jun-2025 13:19:08",
        revised_Date="14-JUN-2025 13:19:06",
        revision_Remark="RPT disclosure revised; no change in values.",
        xbrl="https://x/revision.xml",
    )
    sel = dl.select_xbrl([revision, original], 2025, consolidated=False)
    assert sel is not None and sel.url == "https://x/revision.xml"
    assert "Revision" in sel.warnings[0] and "no change in values" in sel.warnings[0]


# --- rate limiting and HTTP ------------------------------------------------------


def test_rate_limiter_enforces_min_interval() -> None:
    t = FakeTime()
    limiter = dl.RateLimiter(min_interval=2.0, clock=t.clock, sleep=t.sleep)
    limiter.wait()
    t.now += 0.5
    limiter.wait()
    limiter.wait()
    assert t.slept == [pytest.approx(1.5), pytest.approx(2.0)]


def test_blocked_response_raises(tmp_path: Path) -> None:
    client = make_client(FakeNse(status=403))
    with pytest.raises(dl.NseBlockedError):
        dl.ingest("TCS", 2025, client, root=tmp_path)


def test_requests_send_browser_user_agent(tmp_path: Path) -> None:
    fake = FakeNse()
    dl.ingest("TCS", 2025, make_client(fake), root=tmp_path)
    assert all(r.headers["User-Agent"] == dl.USER_AGENT for r in fake.requests)


def test_failed_download_leaves_no_partial_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection reset", request=request)

    client = dl.NseClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.limiter = dl.RateLimiter(min_interval=0)
    dest = tmp_path / "annual_report.pdf"
    with pytest.raises(dl.NseBlockedError):
        client.download("https://nsearchives.nseindia.com/a.pdf", dest)
    assert list(tmp_path.iterdir()) == []


# --- ingest -------------------------------------------------------------------------


def test_ingest_downloads_all_files_with_provenance(tmp_path: Path) -> None:
    res = dl.ingest("TCS", 2025, make_client(FakeNse()), root=tmp_path)
    folder = tmp_path / "TCS" / "FY2025"
    assert res.missing == [] and res.warnings == []
    assert sorted(res.downloaded) == sorted([dl.AR_PDF, *dl.XBRL_FILES.values()])
    manifest = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    entry = manifest["files"]["results_consolidated.xml"]
    assert entry["url"].endswith("INTEGRATED_FILING_INDAS_1412101_11042025074137_WEB.xml")
    assert len(entry["sha256"]) == 64 and entry["nse"]["qe_Date"] == "31-MAR-2025"
    assert (folder / "annual_report.pdf").read_bytes() == PDF_BYTES


def test_second_ingest_makes_no_requests(tmp_path: Path) -> None:
    dl.ingest("TCS", 2025, make_client(FakeNse()), root=tmp_path)
    fake = FakeNse()
    res = dl.ingest("TCS", 2025, make_client(fake), root=tmp_path)
    assert fake.requests == []
    assert res.downloaded == [] and len(res.cached) == 3


def test_ingest_extracts_single_pdf_from_zip(tmp_path: Path) -> None:
    res = dl.ingest("TCS", 2024, make_client(FakeNse()), root=tmp_path)
    folder = tmp_path / "TCS" / "FY2024"
    assert (folder / "annual_report.pdf").read_bytes() == PDF_BYTES
    assert (folder / "annual_report.zip").exists()
    manifest = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    assert manifest["files"]["annual_report.pdf"]["extracted_from"] == "annual_report.zip"
    assert res.missing == []


def test_ingest_zip_with_several_pdfs_is_flagged_not_guessed(tmp_path: Path) -> None:
    zip_bytes = make_zip({"part1.pdf": PDF_BYTES, "part2.pdf": PDF_BYTES})
    res = dl.ingest("TCS", 2023, make_client(FakeNse(zip_bytes=zip_bytes)), root=tmp_path)
    folder = tmp_path / "TCS" / "FY2023"
    assert not (folder / "annual_report.pdf").exists()
    assert res.missing == ["annual_report.pdf"]
    assert any("contains 2 PDFs" in w for w in res.warnings)
    manifest = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    assert any("contains 2 PDFs" in w for w in manifest["warnings"])
