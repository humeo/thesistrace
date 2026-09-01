from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Never

from production_mcp_image_canaries import CANARY_CATEGORIES, SENSITIVE_CANARIES

TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".txt", ".xml"}
REDACTION = b"<redacted>"
READ_CHUNK_BYTES = 64 * 1024
ENCODED_CANARIES = tuple(canary.encode() for canary in SENSITIVE_CANARIES)
# Detect real signed OAuth tokens too, not only deterministic test stand-ins.
# Bounds keep cross-chunk matching and evidence redaction memory-limited.
TOKEN_PATTERN = re.compile(
    rb"eyJ[A-Za-z0-9_-]{4,8192}\.eyJ[A-Za-z0-9_-]{4,8192}\.[A-Za-z0-9_-]{10,2048}"
)
CANARY_OVERLAP_BYTES = max(32 * 1024, max(len(canary) for canary in ENCODED_CANARIES) - 1)
HTML_LIMIT_BYTES = 64 * 1024 * 1024
ARCHIVE_LIMIT_BYTES = 256 * 1024 * 1024
EMBEDDED_REPORT_PATTERN = re.compile(rb'data:application/zip;base64,([^<"\s\']*)')


class EvidenceSanitizationError(RuntimeError):
    pass


def scan_raw_evidence(root: Path) -> list[dict[str, object]]:
    """Detect before redaction; reports contain closed categories, never values."""
    findings: list[dict[str, object]] = []
    for path in _evidence_files(root):
        try:
            categories = _matching_categories(path)
        except (OSError, ValueError, zipfile.BadZipFile):
            raise EvidenceSanitizationError("raw_scan_unavailable") from None
        if categories:
            name = path.name
            services = {
                "agent-events.jsonl": "agent",
                "auth-events.jsonl": "auth",
                "api-events.jsonl": "core",
                "caddy-events.jsonl": "caddy",
                "worker-events.jsonl": "workers",
                "compose-logs.txt": "compose",
            }
            label = (
                name
                if name in services
                else "diagnostic-"
                + hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:12]
            )
            findings.append(
                {
                    "file": label,
                    "service": services.get(name, "diagnostic"),
                    "categories": sorted(categories),
                }
            )
    return findings


def sanitize_evidence(root: Path) -> None:
    for path in _evidence_files(root):
        if path.suffix not in TEXT_SUFFIXES:
            try:
                if _contains_canary(path):
                    path.unlink()
            except OSError as error:
                raise EvidenceSanitizationError(type(error).__name__) from None
            continue
        temporary = path.with_name(f".{path.name}.redacted")
        try:
            _write_sanitized_text(path, temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise EvidenceSanitizationError(type(error).__name__) from None
    verify_evidence(root)


def verify_evidence(root: Path) -> None:
    for path in _evidence_files(root):
        try:
            contains_canary = _contains_canary(path)
        except OSError as error:
            raise EvidenceSanitizationError(type(error).__name__) from None
        if contains_canary:
            raise EvidenceSanitizationError("sensitive_canary_present")


def discard_evidence(root: Path) -> None:
    failures: list[str] = []
    for path in _evidence_files(root):
        try:
            path.unlink()
        except OSError as error:
            failures.append(type(error).__name__)
    if failures:
        raise EvidenceSanitizationError(failures[0])


def _evidence_files(root: Path) -> list[Path]:
    try:
        return sorted(path for path in root.rglob("*") if path.is_file())
    except OSError as error:
        raise EvidenceSanitizationError(type(error).__name__) from None


def _contains_canary(path: Path) -> bool:
    return bool(_matching_categories(path))


def _stream_categories(stream: BinaryIO) -> set[str]:
    pending = b""
    found: set[str] = set()
    while chunk := stream.read(READ_CHUNK_BYTES):
        window = pending + chunk
        found.update(
            CANARY_CATEGORIES[value.decode()] for value in ENCODED_CANARIES if value in window
        )
        if TOKEN_PATTERN.search(window):
            found.add("access_token")
        pending = window[-CANARY_OVERLAP_BYTES:]
    return found


def _matching_categories(path: Path) -> set[str]:
    try:
        return _file_categories(path)
    except EvidenceSanitizationError:
        raise
    except Exception:
        # Archive/decoder errors may contain entry names or private paths.
        # Unknown codec failures fail closed too; they never become a raw
        # traceback in any caller, including sanitize/verify and the CLI.
        raise EvidenceSanitizationError("evidence_scan_unavailable") from None


def _file_categories(path: Path) -> set[str]:
    with path.open("rb") as stream:
        found = _stream_categories(stream)
    # Playwright traces are compressed; searching zip bytes alone misses their
    # request bodies. Inspect bounded entries in memory, never extract paths.
    if path.suffix == ".zip" and zipfile.is_zipfile(path):
        found.update(_archive_categories(path))
    if path.suffix == ".html":
        with path.open("rb") as stream:
            html = stream.read(HTML_LIMIT_BYTES + 1)
        if len(html) > HTML_LIMIT_BYTES:
            raise EvidenceSanitizationError("report_html_too_large")
        # The retained Playwright HTML contains a base64 ZIP even when there
        # is no separate trace.zip. Scan that content before any redaction too.
        for match in EMBEDDED_REPORT_PATTERN.finditer(html):
            with BytesIO(base64.b64decode(match.group(1), validate=True)) as report:
                found.update(_stream_categories(report))
                report.seek(0)
                found.update(_archive_categories(report))
    return found


def _archive_categories(source: Path | BytesIO) -> set[str]:
    found: set[str] = set()
    with zipfile.ZipFile(source) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > ARCHIVE_LIMIT_BYTES:
            raise EvidenceSanitizationError("trace_archive_too_large")
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            with archive.open(entry) as stream:
                found.update(_stream_categories(stream))
    return found


def _write_sanitized_text(source: Path, target: Path) -> None:
    pending = b""
    with source.open("rb") as source_stream, target.open("wb") as target_stream:
        while chunk := source_stream.read(READ_CHUNK_BYTES):
            window = pending + chunk
            if len(window) <= CANARY_OVERLAP_BYTES:
                pending = window
                continue
            split = len(window) - CANARY_OVERLAP_BYTES
            # Keep the original tail until the next read. Redacting a partial
            # variable-length token now would expose its remaining signature
            # bytes in the next chunk. Never split a sensitive span either.
            for start, end in sorted(_sensitive_spans(window), reverse=True):
                if start < split < end:
                    split = start
            target_stream.write(_redact(window[:split]))
            pending = window[split:]
        target_stream.write(_redact(pending))


def _sensitive_spans(value: bytes) -> list[tuple[int, int]]:
    spans = [match.span() for match in TOKEN_PATTERN.finditer(value)]
    for canary in ENCODED_CANARIES:
        start = value.find(canary)
        while start >= 0:
            spans.append((start, start + len(canary)))
            start = value.find(canary, start + len(canary))
    return spans


def _redact(value: bytes) -> bytes:
    cursor = 0
    result = bytearray()
    for start, end in sorted(_sensitive_spans(value)):
        if end <= cursor:
            continue
        if start >= cursor:
            result.extend(value[cursor:start])
            result.extend(REDACTION)
        cursor = end
    result.extend(value[cursor:])
    return bytes(result)


def _exit_failed(error: EvidenceSanitizationError) -> Never:
    print(f"evidence_sanitization_failed:{error}", file=sys.stderr)
    raise SystemExit(2) from None


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"discard", "sanitize", "verify", "scan"}:
        raise SystemExit(
            "usage: sanitize_production_mcp_evidence.py {discard|sanitize|verify|scan} EVIDENCE_DIR"
        )
    root = Path(sys.argv[2])
    try:
        if sys.argv[1] == "scan":
            findings = scan_raw_evidence(root)
            print(json.dumps({"status": "failed" if findings else "passed", "findings": findings}))
            if findings:
                raise SystemExit(1)
        elif sys.argv[1] == "sanitize":
            sanitize_evidence(root)
        elif sys.argv[1] == "verify":
            verify_evidence(root)
        else:
            discard_evidence(root)
    except EvidenceSanitizationError as error:
        _exit_failed(error)


if __name__ == "__main__":
    main()
