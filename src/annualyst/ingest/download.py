"""Download annual reports and XBRL financial results from NSE into data/raw/{SYMBOL}/FY{FY}/.

Layout per company-year:
    annual_report.pdf          the annual report (unpacked from annual_report.zip if needed)
    results_consolidated.xml   XBRL financial results, consolidated
    results_standalone.xml     XBRL financial results, standalone
    source.json                provenance: source URLs, NSE metadata, sha256, warnings

Usage:
    python -m annualyst.ingest.download --symbol TCS --fy 2025
    python -m annualyst.ingest.download            # all COMPANIES x FISCAL_YEARS
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

COMPANIES = ("TCS", "INFY", "HINDUNILVR", "ASIANPAINT", "RELIANCE")
FISCAL_YEARS = (2023, 2024, 2025)
RAW_ROOT = Path("data/raw")

NSE_BASE = "https://www.nseindia.com"
# NSE's bot filter drops connections from non-browser User-Agents (checked 2026-10-10), so we
# send a browser UA. Agreed exception to CLAUDE.md rule 9: still rate-limited, cached, and we
# stop if blocked.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": f"{NSE_BASE}/",
    "Accept": "application/json, application/pdf, application/xml, */*",
}
MIN_INTERVAL_S = 2.0

# From the quarter ended March 2025, results are filed under SEBI's "Integrated Filing" and no
# longer appear in the legacy financial-results API.
FIRST_INTEGRATED_FY = 2025
INTEGRATED_TYPE = "Integrated Filing- Financials"

AR_PDF = "annual_report.pdf"
AR_ZIP = "annual_report.zip"
XBRL_FILES = {True: "results_consolidated.xml", False: "results_standalone.xml"}
MANIFEST = "source.json"


class NseBlockedError(RuntimeError):
    """NSE refused or dropped a request. We stop instead of retrying."""


class RateLimiter:
    """Guarantees at least `min_interval` seconds between consecutive requests."""

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.min_interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


class NseClient:
    """Rate-limited NSE client. JSON responses are cached to disk; files stream via a .part file."""

    def __init__(
        self, http: httpx.Client | None = None, limiter: RateLimiter | None = None
    ) -> None:
        self.http = http or httpx.Client(timeout=60.0, follow_redirects=True)
        self.limiter = limiter or RateLimiter()

    def get_json(self, path: str, params: dict[str, str], cache_file: Path) -> Any:
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        self.limiter.wait()
        try:
            resp = self.http.get(f"{NSE_BASE}{path}", params=params, headers=HEADERS)
        except httpx.TransportError as exc:
            raise NseBlockedError(f"request to {path} failed: {exc!r}") from exc
        _check_status(resp)
        data = resp.json()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return data

    def download(self, url: str, dest: Path) -> None:
        self.limiter.wait()
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.http.stream("GET", url, headers=HEADERS) as resp:
                _check_status(resp)
                with part.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        except httpx.TransportError as exc:
            part.unlink(missing_ok=True)
            raise NseBlockedError(f"download of {url} failed: {exc!r}") from exc
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)


def _check_status(resp: httpx.Response) -> None:
    if resp.status_code in (401, 403):
        raise NseBlockedError(f"HTTP {resp.status_code} from {resp.request.url}")
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Selecting the right filing from NSE's listings (pure functions)
# ---------------------------------------------------------------------------


def fy_bounds(fy: int) -> tuple[date, date]:
    """FY2025 = 1 Apr 2024 to 31 Mar 2025 (Indian fiscal year)."""
    return date(fy - 1, 4, 1), date(fy, 3, 31)


def _parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(value or "", "%d-%b-%Y").date()
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime:
    """Parse NSE broadcast timestamps like '12-Apr-2024 21:04:39'; '-' or None sorts first."""
    try:
        return datetime.strptime(value or "", "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return datetime.min


@dataclass
class Selection:
    url: str
    entry: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _filed_at(entry: dict[str, Any], date_keys: tuple[str, ...]) -> datetime:
    # Revisions on the integrated-filing API have broadcast_Date=None and carry their date in
    # revised_Date, so take the latest of all date fields NSE gives.
    return max(_parse_datetime(entry.get(k)) for k in date_keys)


def _pick_latest(
    matches: list[dict[str, Any]], url_key: str, date_keys: tuple[str, ...], what: str
) -> Selection | None:
    if not matches:
        return None
    best = max(matches, key=lambda e: _filed_at(e, date_keys))
    warnings = []
    if len(matches) > 1:
        others = ", ".join(e[url_key] for e in matches if e is not best)
        remark = f" NSE remark: {best['revision_Remark']}" if best.get("revision_Remark") else ""
        warnings.append(
            f"{len(matches)} filings found for {what}; using the latest "
            f"({_filed_at(best, date_keys):%d-%b-%Y %H:%M}, {best.get('type_Sub', 'filing')}). "
            f"Not used: {others}.{remark}"
        )
    return Selection(url=best[url_key], entry=best, warnings=warnings)


def select_annual_report(entries: list[dict[str, Any]], fy: int) -> Selection | None:
    matches = [e for e in entries if e.get("fromYr") == str(fy - 1) and e.get("toYr") == str(fy)]
    return _pick_latest(matches, "fileName", ("broadcast_dttm",), f"annual report FY{fy}")


def select_xbrl(entries: list[dict[str, Any]], fy: int, consolidated: bool) -> Selection | None:
    """Pick the full-year results XBRL for `fy`.

    `entries` comes from the legacy results API for FY < FIRST_INTEGRATED_FY and from the
    integrated-filing API otherwise; the two use different field names.
    """
    start, end = fy_bounds(fy)
    view = "consolidated" if consolidated else "standalone"
    what = f"{view} XBRL FY{fy}"
    if fy >= FIRST_INTEGRATED_FY:
        label = "Consolidated" if consolidated else "Standalone"
        matches = [
            e
            for e in entries
            if e.get("type") == INTEGRATED_TYPE
            and _parse_date(e.get("qe_Date")) == end
            and e.get("consolidated") == label
            and _has_xbrl(e)
        ]
        date_keys = ("broadcast_Date", "revised_Date", "creation_Date")
        return _pick_latest(matches, "xbrl", date_keys, what)
    label = "Consolidated" if consolidated else "Non-Consolidated"
    matches = [
        e
        for e in entries
        if e.get("period") == "Annual"
        and _parse_date(e.get("fromDate")) == start
        and _parse_date(e.get("toDate")) == end
        and e.get("consolidated") == label
        and _has_xbrl(e)
    ]
    return _pick_latest(matches, "xbrl", ("broadCastDate",), what)


def _has_xbrl(entry: dict[str, Any]) -> bool:
    # NSE lists filings without XBRL with a URL ending in "/-".
    url = entry.get("xbrl") or ""
    return url.endswith(".xml")


# ---------------------------------------------------------------------------
# Ingest one company-year
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    symbol: str
    fy: int
    downloaded: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _record(manifest: dict[str, Any], name: str, path: Path, url: str, entry: dict | None) -> None:
    manifest["files"][name] = {
        "url": url,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "nse": entry,
    }


def _extract_pdf_from_zip(zip_path: Path, dest: Path) -> list[str]:
    """Extract the zip's single PDF to `dest`. Returns warnings (non-empty: nothing extracted)."""
    with zipfile.ZipFile(zip_path) as zf:
        pdfs = [
            n for n in zf.namelist() if n.lower().endswith(".pdf") and not n.startswith("__MACOSX/")
        ]
        if len(pdfs) != 1:
            return [
                f"{zip_path.name} contains {len(pdfs)} PDFs, so annual_report.pdf was not created. "
                f"Decide which to use: {zf.namelist()}"
            ]
        # Write to a fixed name rather than extracting member paths (avoids zip path traversal).
        dest.write_bytes(zf.read(pdfs[0]))
    return []


class _Listings:
    """Lazily fetched NSE listings for one symbol (each is at most one request, then cached)."""

    def __init__(self, client: NseClient, symbol: str, cache_dir: Path) -> None:
        self.client, self.symbol, self.cache_dir = client, symbol, cache_dir
        self.warnings: list[str] = []
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def _get(self, key: str, path: str, params: dict[str, str]) -> Any:
        cache_file = self.cache_dir / f"{self.symbol}_{key}.json"
        return self.client.get_json(
            path, {"index": "equities", "symbol": self.symbol, **params}, cache_file
        )

    def annual_reports(self) -> list[dict[str, Any]]:
        if "ar" not in self._cache:
            self._cache["ar"] = self._get("annual_reports", "/api/annual-reports", {})["data"]
        return self._cache["ar"]

    def results(self, fy: int) -> list[dict[str, Any]]:
        if fy < FIRST_INTEGRATED_FY:
            if "legacy" not in self._cache:
                self._cache["legacy"] = self._get(
                    "results_legacy", "/api/corporates-financial-results", {"period": "Annual"}
                )
            return self._cache["legacy"]
        if "integrated" not in self._cache:
            data = self._get(
                "results_integrated",
                "/api/integrated-filing-results",
                {"type": INTEGRATED_TYPE, "size": "100"},
            )
            if data.get("totalCount", 0) > len(data["data"]):
                self.warnings.append(
                    f"integrated-filing listing truncated ({len(data['data'])} of "
                    f"{data['totalCount']}); older filings may be missing"
                )
            self._cache["integrated"] = data["data"]
        return self._cache["integrated"]


def ingest(
    symbol: str,
    fy: int,
    client: NseClient,
    root: Path = RAW_ROOT,
    listings: _Listings | None = None,
) -> IngestResult:
    folder = root / symbol / f"FY{fy}"
    manifest_path = folder / MANIFEST
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"symbol": symbol, "fiscal_year": fy, "files": {}, "warnings": []}
    listings = listings or _Listings(client, symbol, root / "_api_cache")
    result = IngestResult(symbol, fy)

    def is_cached(name: str) -> bool:
        return (folder / name).exists() and name in manifest["files"]

    # Annual report
    if is_cached(AR_PDF):
        result.cached.append(AR_PDF)
    else:
        sel = select_annual_report(listings.annual_reports(), fy)
        if sel is None:
            result.missing.append(AR_PDF)
            result.warnings.append(f"no annual report for FY{fy} in NSE listing")
        else:
            result.warnings += sel.warnings
            if sel.url.lower().endswith(".zip"):
                if is_cached(AR_ZIP):
                    result.cached.append(AR_ZIP)
                else:
                    client.download(sel.url, folder / AR_ZIP)
                    _record(manifest, AR_ZIP, folder / AR_ZIP, sel.url, sel.entry)
                    result.downloaded.append(AR_ZIP)
                zip_warnings = _extract_pdf_from_zip(folder / AR_ZIP, folder / AR_PDF)
                if zip_warnings:
                    result.warnings += zip_warnings
                    result.missing.append(AR_PDF)
                else:
                    _record(manifest, AR_PDF, folder / AR_PDF, sel.url, sel.entry)
                    manifest["files"][AR_PDF]["extracted_from"] = AR_ZIP
                    result.downloaded.append(AR_PDF)
            elif sel.url.lower().endswith(".pdf"):
                client.download(sel.url, folder / AR_PDF)
                _record(manifest, AR_PDF, folder / AR_PDF, sel.url, sel.entry)
                result.downloaded.append(AR_PDF)
            else:
                result.missing.append(AR_PDF)
                result.warnings.append(f"annual report has an unexpected file type: {sel.url}")

    # XBRL results, consolidated and standalone
    for consolidated, name in XBRL_FILES.items():
        if is_cached(name):
            result.cached.append(name)
            continue
        sel = select_xbrl(listings.results(fy), fy, consolidated)
        if sel is None:
            result.missing.append(name)
            result.warnings.append(f"no {name} filing for FY{fy} on NSE")
            continue
        result.warnings += sel.warnings
        client.download(sel.url, folder / name)
        _record(manifest, name, folder / name, sel.url, sel.entry)
        result.downloaded.append(name)

    result.warnings += listings.warnings
    if result.downloaded or result.warnings:
        manifest["warnings"] = sorted(set(manifest["warnings"]) | set(result.warnings))
        folder.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_fy(value: str) -> int:
    """Accept '2025' or 'FY2025'."""
    return int(value.upper().removeprefix("FY"))


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

    symbols = [args.symbol.upper()] if args.symbol else list(COMPANIES)
    years = [args.fy] if args.fy else list(FISCAL_YEARS)
    client = NseClient()
    any_missing = False
    for symbol in symbols:
        listings = _Listings(client, symbol, args.root / "_api_cache")
        for fy in years:
            try:
                res = ingest(symbol, fy, client, args.root, listings)
            except NseBlockedError as exc:
                print(f"{symbol} FY{fy}: STOPPED - NSE blocked scripted access ({exc}).")
                print(
                    f"Download the files manually into {args.root / symbol / f'FY{fy}'}/ "
                    "and run `make validate`."
                )
                return 2
            status = "missing " + ", ".join(res.missing) if res.missing else "ok"
            print(
                f"{symbol} FY{fy}: {status} "
                f"(downloaded {len(res.downloaded)}, cached {len(res.cached)})"
            )
            for w in res.warnings:
                print(f"    warning: {w}")
            any_missing |= bool(res.missing)
    return 1 if any_missing else 0


if __name__ == "__main__":
    sys.exit(main())
