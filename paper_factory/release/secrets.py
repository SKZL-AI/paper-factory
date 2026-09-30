"""Secret scanner: pattern + entropy based, fails closed.

'Fails closed' means: anything suspicious blocks the release; a scanner error
also blocks. Files of any size are streamed in chunks with a boundary overlap,
so large artifacts cannot escape the scan; a symlink inside the scanned tree
fails the scan outright. There is no 'probably fine' and no 'too big to check'.

Encoding strategy: a file whose probe is clean UTF-8 without NULs is scanned
as text; every other file — and every text file that turns out to contain
NULs or undecodable bytes deeper in the stream — is scanned in byte space
under every supported reading at once: latin-1 (byte identity, catches
ASCII/UTF-8/Latin-1 secrets), UTF-16-LE/BE at both parities, and UTF-32-LE/BE
at all four parities. The views are NOT gated on any density heuristic —
a gate is itself a classification an attacker can split a payload around.
(Linear cost: ~13 passes per non-text file; a release gate may take seconds.)
"""
from __future__ import annotations

import codecs
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PATTERNS = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("github_pat", re.compile(r"(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}")),
    ("huggingface", re.compile(r"hf_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]

CHUNK_SIZE = 1 << 20  # 1 MiB raw reads — large files are streamed, never skipped
# Look-back carried across chunk edges so a secret straddling a boundary is
# still matched whole. Realistic credentials are a few hundred bytes at most;
# 8 KiB covers them with an order of magnitude to spare.
BOUNDARY_OVERLAP = 8192
_PROBE_BYTES = 8192


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) / len(s) for c in set(s)}
    return -sum(p * math.log2(p) for p in freq.values())


_ASSIGNMENT = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|passphrase)\s*[:=]\s*[\"'<{]{0,2}"
    r"([A-Za-z0-9._~+/-]{16,})[\"'>}]{0,2}", re.IGNORECASE)


def _scan_text(text: str, relpath: str, via: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            findings.append({"file": relpath, "kind": name, "via": via,
                             "span": [m.start(), m.end()]})
    for m in _ASSIGNMENT.finditer(text):
        value = m.group(1)
        if _entropy(value) > 3.5:
            findings.append({"file": relpath, "kind": "high_entropy_assignment",
                             "via": via, "span": [m.start(1), m.end(1)]})
    return findings


def scan_text(text: str, relpath: str) -> list[dict[str, Any]]:
    """Single-shot scan of a decoded text (used by the streaming scanner per
    window; kept public for callers with in-memory text)."""
    return _scan_text(text, relpath, "text")


class _NulBytes(Exception):
    """A file classified as clean text turned out to contain NUL bytes."""


def _scan_windows(chunks: Iterable[str], relpath: str, via: str) -> list[dict[str, Any]]:
    """Scan a stream of text chunks with BOUNDARY_OVERLAP look-back. A match is
    reported in the first window that contains it completely (its end must
    reach into the newest chunk); same-start duplicates from a match growing
    across a boundary are collapsed afterwards in scan_file.
    """
    findings: list[dict[str, Any]] = []
    tail = ""
    new_start = 0  # absolute offset at which the current chunk begins
    for chunk in chunks:
        if not chunk:
            continue
        window = tail + chunk
        origin = new_start - len(tail)
        for f in _scan_text(window, relpath, via):
            end = origin + f["span"][1]
            if end > new_start:
                f["span"] = [origin + f["span"][0], end]
                findings.append(f)
        tail = window[-BOUNDARY_OVERLAP:]
        new_start += len(chunk)
    return findings


def _dedupe(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One (view, kind, start) pair is reported once, with the longest span —
    a token that keeps growing across a chunk boundary must not double-count."""
    best: dict[tuple[str, str, int], dict[str, Any]] = {}
    for f in findings:
        key = (f["via"], f["kind"], f["span"][0])
        if key not in best or f["span"][1] > best[key]["span"][1]:
            best[key] = f
    return sorted(best.values(), key=lambda f: (f["file"], f["span"][0], f["kind"]))


def _byte_chunks(path: Path, size: int = CHUNK_SIZE) -> Iterable[bytes]:
    with path.open("rb") as fh:
        while True:
            block = fh.read(size)
            if not block:
                return
            yield block


def _utf8_chunks_guarded(path: Path) -> Iterable[str]:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    for block in _byte_chunks(path):
        text = decoder.decode(block)
        if "\x00" in text:
            raise _NulBytes  # not plain text after all → byte paths take over
        if text:
            yield text
    tail = decoder.decode(b"", True)
    if tail:
        yield tail


def _decoded_chunks(path: Path, encoding: str, skip: int = 0) -> Iterable[str]:
    """Stream `path` decoded as `encoding`, dropping `skip` leading bytes
    (alignment parity for mixed-content files). Decode errors are replaced —
    this is a detection view, not a parser."""
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    first = True
    for block in _byte_chunks(path):
        if first:
            block = block[skip:]
            first = False
        text = decoder.decode(block)
        if text:
            yield text
    tail = decoder.decode(b"", True)
    if tail:
        yield tail


def scan_file(path: Path, relpath: str) -> dict[str, Any]:
    """Scan one file completely, streamed. Returns findings plus how the file
    was read: 'utf-8' for the clean-text path, 'bytes' when the byte-space
    views ran (fallback=True). The byte path always runs every view — no
    density gate: any gate is a classification a payload can be split around.
    """
    with path.open("rb") as fh:
        probe = fh.read(_PROBE_BYTES)
    try:
        is_text = "\x00" not in probe.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        is_text = False
    if is_text:
        try:
            findings = _scan_windows(_utf8_chunks_guarded(path), relpath, "utf-8")
            return {"findings": _dedupe(findings), "encoding": "utf-8", "fallback": False}
        except (UnicodeDecodeError, _NulBytes):
            pass  # mixed/corrupt content → byte paths below see everything

    findings: list[dict[str, Any]] = []
    # latin-1 is byte identity: offsets stay exact, ASCII/UTF-8/Latin-1
    # secrets are caught regardless of any surrounding binary content
    findings += _scan_windows((b.decode("latin-1") for b in _byte_chunks(path)),
                              relpath, "bytes")
    for enc in ("utf-16-le", "utf-16-be"):
        for skip in (0, 1):
            findings += _scan_windows(_decoded_chunks(path, enc, skip),
                                      relpath, f"{enc}+{skip}")
    for enc in ("utf-32-le", "utf-32-be"):
        for skip in range(4):
            findings += _scan_windows(_decoded_chunks(path, enc, skip),
                                      relpath, f"{enc}+{skip}")
    return {"findings": _dedupe(findings), "encoding": "bytes", "fallback": True}


def scan_tree(root: Path, *, include_globs: tuple[str, ...] = ("**/*",),
              exclude_dirs: tuple[str, ...] = (".git", "node_modules", "__pycache__", ".venv")) -> dict[str, Any]:
    """Scan every file under root. Callers that need full coverage of a tree
    (the release bundle!) must pass exclude_dirs=() — the default exclusions
    exist for arbitrary workspace trees and are NOT a release-grade choice.
    """
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    symlinks: list[str] = []
    fallbacks: list[str] = []
    scanned = 0
    if not root.is_dir():
        # fail closed: there is no 'nothing to scan, so nothing found'
        return {"scanned_root": str(root), "scanned_files": 0, "findings": [],
                "errors": [f"scan root missing or not a directory: {root}"],
                "symlinks": [], "encoding_fallbacks": [], "verdict": "FAIL"}
    for pattern in include_globs:
        for p in sorted(root.glob(pattern)):
            if any(d in p.parts for d in exclude_dirs):
                continue
            if p.is_symlink():
                # fail closed: a symlink inside the scanned tree is never
                # followed and never silently skipped
                symlinks.append(str(p.relative_to(root)))
                continue
            if p.is_dir():
                continue
            if not p.is_file():
                # FIFOs, sockets, device nodes: unscannable content → block
                errors.append(f"{p.relative_to(root)}: not a regular file")
                continue
            rel = str(p.relative_to(root))
            try:
                result = scan_file(p, rel)
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
                continue
            scanned += 1
            findings.extend(result["findings"])
            if result["fallback"]:
                fallbacks.append(f"{rel} (byte views)")
    # fail closed: findings, unreadable/unscannable files or symlinks in the
    # scanned tree all block. Nothing is skipped for size — files are streamed.
    verdict = "FAIL" if findings or errors or symlinks else "PASS"
    return {"scanned_root": str(root), "scanned_files": scanned, "findings": findings,
            "errors": errors, "symlinks": symlinks, "encoding_fallbacks": fallbacks,
            "verdict": verdict}
