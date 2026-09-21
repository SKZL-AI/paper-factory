"""Secret scanner: pattern + entropy based, fails closed.

'Fails closed' means: anything suspicious blocks the release; a scanner error
also blocks. There is no 'probably fine'.
"""
from __future__ import annotations

import math
import re
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
# byte-level variants of the high-signal patterns, for binary/unreadable files
BYTE_PATTERNS = [(name, re.compile(p.pattern.encode())) for name, p in PATTERNS]


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) / len(s) for c in set(s)}
    return -sum(p * math.log2(p) for p in freq.values())


_ASSIGNMENT = re.compile(r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*[\"']?([A-Za-z0-9._~+/-]{16,})[\"']?",
                         re.I)


def scan_text(text: str, relpath: str) -> list[dict[str, Any]]:
    findings = []
    for name, pat in PATTERNS:
        for m in pat.finditer(text):
            findings.append({"file": relpath, "kind": name, "span": [m.start(), m.end()]})
    for m in _ASSIGNMENT.finditer(text):
        value = m.group(1)
        if _entropy(value) > 3.5 and not value.startswith(("<", "{", "PAPER_FACTORY")):
            findings.append({"file": relpath, "kind": "high_entropy_assignment",
                             "span": [m.start(1), m.end(1)]})
    return findings


def scan_tree(root: Path, *, include_globs: tuple[str, ...] = ("**/*",),
              exclude_dirs: tuple[str, ...] = (".git", "node_modules", "__pycache__", ".venv")) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    errors: list[str] = []
    skipped: list[str] = []
    scanned = 0
    for pattern in include_globs:
        for p in sorted(root.glob(pattern)):
            if not p.is_file() or p.is_symlink() or any(d in p.parts for d in exclude_dirs):
                if p.is_symlink():
                    skipped.append(f"{p.relative_to(root)} (symlink)")
                continue
            if p.stat().st_size > 5_000_000:
                skipped.append(f"{p.relative_to(root)} (>5MB)")
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="strict")
            except UnicodeDecodeError:
                # UTF-16 (NUL-interleaved) decodes to text that patterns can match
                try:
                    text = p.read_text(encoding="utf-16")
                    scanned += 1
                    findings.extend(scan_text(text, str(p.relative_to(root))))
                    continue
                except (UnicodeDecodeError, UnicodeError):
                    pass
                # binary: byte-level scan with the high-signal patterns
                try:
                    blob = p.read_bytes()
                    scanned += 1
                    for name, pat in BYTE_PATTERNS:
                        for m in pat.finditer(blob):
                            findings.append({"file": str(p.relative_to(root)), "kind": name,
                                             "span": [m.start(), m.end()], "binary": True})
                except OSError as exc:
                    errors.append(f"{p.relative_to(root)}: {exc}")
                continue
            except OSError as exc:
                errors.append(f"{p.relative_to(root)}: {exc}")
                continue
            scanned += 1
            findings.extend(scan_text(text, str(p.relative_to(root))))
    # fail closed: findings OR unreadable files fail; skips degrade honestly
    verdict = "FAIL" if findings or errors else ("DEGRADED" if skipped else "PASS")
    return {"scanned_files": scanned, "findings": findings, "errors": errors,
            "skipped": skipped, "verdict": verdict}
