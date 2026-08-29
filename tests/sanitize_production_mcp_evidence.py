from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Never

from production_mcp_image_canaries import SENSITIVE_CANARIES

TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".txt", ".xml"}
REDACTION = b"<redacted>"
READ_CHUNK_BYTES = 64 * 1024
ENCODED_CANARIES = tuple(canary.encode() for canary in SENSITIVE_CANARIES)
CANARY_OVERLAP_BYTES = max(len(canary) for canary in ENCODED_CANARIES) - 1


class EvidenceSanitizationError(RuntimeError):
    pass


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
    pending = b""
    with path.open("rb") as stream:
        while chunk := stream.read(READ_CHUNK_BYTES):
            window = pending + chunk
            if any(canary in window for canary in ENCODED_CANARIES):
                return True
            pending = window[-CANARY_OVERLAP_BYTES:]
    return False


def _write_sanitized_text(source: Path, target: Path) -> None:
    pending = b""
    with source.open("rb") as source_stream, target.open("wb") as target_stream:
        while chunk := source_stream.read(READ_CHUNK_BYTES):
            window = pending + chunk
            for canary in ENCODED_CANARIES:
                window = window.replace(canary, REDACTION)
            if len(window) <= CANARY_OVERLAP_BYTES:
                pending = window
                continue
            split = len(window) - CANARY_OVERLAP_BYTES
            target_stream.write(window[:split])
            pending = window[split:]
        for canary in ENCODED_CANARIES:
            pending = pending.replace(canary, REDACTION)
        target_stream.write(pending)


def _exit_failed(error: EvidenceSanitizationError) -> Never:
    print(f"evidence_sanitization_failed:{error}", file=sys.stderr)
    raise SystemExit(2) from None


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"discard", "sanitize", "verify"}:
        raise SystemExit(
            "usage: sanitize_production_mcp_evidence.py "
            "{discard|sanitize|verify} EVIDENCE_DIR"
        )
    root = Path(sys.argv[2])
    try:
        if sys.argv[1] == "sanitize":
            sanitize_evidence(root)
        elif sys.argv[1] == "verify":
            verify_evidence(root)
        else:
            discard_evidence(root)
    except EvidenceSanitizationError as error:
        _exit_failed(error)


if __name__ == "__main__":
    main()
