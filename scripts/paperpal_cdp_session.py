#!/usr/bin/env python3
"""Full Paperpal/Word session for P31 (Phase 3 reconciliation).

Stages the CURRENT versioned outbox DOCX, opens Word with WebView2 CDP
debugging, runs the Paperpal Grammar + Consistency checks via CDP (no mouse,
no focus), captures + classifies every suggestion, and delivers the report
into the P31 inbox bound to the EXACT staged DOCX sha256 (production writer —
never hand-written sidecars).

    .venv/bin/python scripts/paperpal_cdp_session.py --root <project>

Capture-only: nothing is applied to the document; Word closes without saving.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paper_factory.core.util import sha256_file, utcnow  # noqa: E402
from paper_factory.paperpal.word.cdp import CDP  # noqa: E402
from paper_factory.paperpal.word.classify import classify_suggestion  # noqa: E402
from paper_factory.paperpal.word.driver import (  # noqa: E402
    WordPaperpalAdapter, stage_docx, wsl_to_win, win_to_wsl, WIN_EXCHANGE)

JS_ARM = r"""(() => {
  window.__pfCards = []; window.__pfSeen = new Set();
  window.__pfCollect = () => {
    document.querySelectorAll('.scroller button, .scroller [role=button]').forEach(b => {
      const t = b.innerText.trim();
      if (t.length > 20 && t.includes('\n') && !window.__pfSeen.has(t)) {
        window.__pfSeen.add(t); window.__pfCards.push(t);
      }
    });
  };
  return 'armed';})()"""

JS_SCROLL = r"""(() => {
  const el = [...document.querySelectorAll('*')].filter(e =>
    e.scrollHeight > e.clientHeight + 50 && e.clientHeight > 200)
    .sort((a,b) => b.scrollHeight - a.scrollHeight)[0];
  if (!el) return JSON.stringify({err: 'no-scroller'});
  window.__pfCollect();
  const before = el.scrollTop;
  el.scrollTop += Math.floor(el.clientHeight * 0.85);
  return JSON.stringify({before, top: el.scrollTop, sh: el.scrollHeight,
                         ch: el.clientHeight});})()"""

JS_COUNTS = r"""(() => {
  const leafs = [...document.querySelectorAll('*')].filter(e => e.children.length === 0);
  const categories = [...new Set(leafs.map(e => e.textContent.trim())
    .filter(t => /^(Grammar|Consistency|Clarity|Word Choice|Verb Form|Determiner|Spelling|Punctuation)/.test(t)
            && t.length < 40))];
  return JSON.stringify({
    cards: document.querySelectorAll('[class*=suggestion], [class*=Suggestion], [class*=card]').length,
    categories,
    buttons: [...document.querySelectorAll('button, [role=button]')]
      .map(e => (e.getAttribute('aria-label') || e.textContent.trim()).slice(0, 50))
      .filter(Boolean)});})()"""


def _ps(cmd: str, timeout: int = 180) -> str:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "").strip()


def _find_cdp_port(not_before: float = 0.0) -> int:
    """The WebView2 user-data dir carries DevToolsActivePort (port + path).
    Stale files from previous Word sessions linger — accept only ports that
    (a) answer /json AND (b) whose port file is fresh (>= our Word start)."""
    import urllib.request

    import os
    _win_user = os.environ.get("PF_WIN_USER", os.environ.get("USER", "user"))
    base = (rf"C:\Users\{_win_user}\AppData\Local\Microsoft\Office\16.0\Wef")
    out = _ps(f'Get-ChildItem -Recurse -Filter DevToolsActivePort "{base}" '
              '| Select-Object -ExpandProperty FullName')
    candidates: list[tuple[float, int]] = []
    for line in out.splitlines():
        p = line.strip()
        if not p:
            continue
        try:
            wsl = win_to_wsl(p)
            mtime = wsl.stat().st_mtime
            content = wsl.read_text().splitlines()
            port = int(content[0].strip())
        except (OSError, ValueError, IndexError):
            continue
        if mtime < not_before:
            continue  # stale file from an earlier Word session
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json",
                                        timeout=3) as r:
                json.loads(r.read().decode())
            candidates.append((mtime, port))
        except Exception:
            continue  # dead port
    if not candidates:
        raise RuntimeError("no live, fresh DevToolsActivePort found")
    candidates.sort()
    return candidates[-1][1]  # newest live port


def _click(cdp: CDP, text: str) -> bool:
    """Click a pane button by VISIBLE label — whitespace-tolerant
    ('ChecksChecks' / 'Checks Checks' / aria-label variants)."""
    needle = text.lower().replace(" ", "")
    return bool(cdp.js(
        "(() => { const els = [...document.querySelectorAll('button, [role=button]')];"
        " const b = els.find(e => {"
        "   const t = (e.textContent || '').trim().toLowerCase().replace(/\\s+/g, '');"
        "   const a = (e.getAttribute('aria-label') || '').toLowerCase().replace(/\\s+/g, '');"
        f"   return t === {json.dumps(needle)} || a === {json.dumps(needle)}"
        f"       || t.startsWith({json.dumps(needle)});"
        " });"
        " if (b) { b.click(); return true; } return false;})()"))


def _collect_cards(cdp: CDP, max_steps: int = 60) -> list[str]:
    cdp.js(JS_ARM)
    last_top, stable = -1, 0
    for _ in range(max_steps):
        st = json.loads(cdp.js(JS_SCROLL))
        if "err" in st:
            break
        if st["top"] == last_top:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last_top = st["top"]
        time.sleep(0.6)
    cdp.js("window.__pfCollect()")
    return cdp.js("JSON.stringify(window.__pfCards)") and json.loads(
        cdp.js("JSON.stringify(window.__pfCards)")) or []


def main() -> int:
    root = Path(sys.argv[sys.argv.index("--root") + 1]).resolve()
    pf = root / ".paper-factory" / "paperpal"
    outbox, inbox = pf / "outbox", pf / "inbox"
    receipts = pf / "receipts"
    ad = WordPaperpalAdapter(receipts_dir=receipts)

    docx = sorted(outbox.glob("paper-*.docx"),
                  key=lambda p: p.stat().st_mtime)[-1]
    staged_sha = sha256_file(docx)
    win = stage_docx(docx)
    ad.record("DOCX_READY", True, f"{docx.name} staged sha={staged_sha[:12]}")
    print(f"[1] staged {docx.name} ({staged_sha[:12]}…)")

    # open Word ownership-scoped (WebView2 CDP flag is set inside the ps1
    # verb; the window is minimized — the operator's session is not disturbed)
    ownership = ad.open_word_owned(win, staged_sha,
                                   run_id=f"paperpal-{utcnow()}")
    print(f"[2] Word opened owned pid={ownership['word_pid']} "
          f"running_before={ownership['word_running_before']} "
          f"foreign_docs={len(ownership['foreign_docs_at_open'])}")

    word_started_at = time.time()
    port = None
    for _ in range(30):
        try:
            port = _find_cdp_port(not_before=word_started_at - 10)
            break
        except Exception:
            time.sleep(2)
    if port is None:
        # pane not open yet: click the Paperpal ribbon via UIA — scoped to
        # OUR Word pid, never another Word window the operator may have open.
        # UIA Invoke needs the window restored (minimized windows swallow
        # clicks) — restore via the recorded hwnd, re-minimize after.
        print("[2b] no CDP port — opening Paperpal pane via pid-owned UIA")
        pid = str(ownership["word_pid"])
        _ps("Add-Type -MemberDefinition '[System.Runtime.InteropServices.DllImport("
            "\"user32.dll\")] public static extern bool ShowWindow(System.IntPtr h, int c);'"
            f" -Name Rst -Namespace PFRst; $p = Get-Process -Id {pid};"
            " [PFRst.Rst]::ShowWindow($p.MainWindowHandle, 9) | Out-Null",
            timeout=30)
        time.sleep(2)
        for name in ("Paperpal", "Open Paperpal"):
            subprocess.run([sys.executable,
                            str(Path(__file__).with_name("run_paperpal_word.py")),
                            "--root", str(root), "uia-click-owned", name, pid],
                           capture_output=True, timeout=120)
            time.sleep(2)
        for _ in range(30):
            try:
                port = _find_cdp_port(not_before=word_started_at - 10)
                break
            except Exception:
                time.sleep(2)
    if port is None:
        ad.record("PAPERPAL_VISIBLE", False, "no CDP port after UIA open")
        ad.write_report(receipts / "paperpal_word_session.json",
                        {"aborted": True, "failure": "no CDP port"})
        print("FAILED: no CDP port", file=sys.stderr)
        return 1

    cdp = CDP(port=port, target_substring="paperpal")
    ad.record("PAPERPAL_VISIBLE", True, f"cdp port {port} target {cdp.target}")
    print(f"[3] CDP attached: {cdp.target.get('title', '')[:60]}")

    # the pane loads asynchronously — wait until the checks UI exists
    ready = False
    for _ in range(45):
        ready = bool(cdp.js(
            "(() => !!([...document.querySelectorAll('button, [role=button]')]"
            ".find(e => { const t = (e.textContent || '').trim().toLowerCase();"
            " return t === 'grammar' || t === 'checks checks' || t === 'checks'; })))()"))
        if ready:
            break
        time.sleep(2)
    if not ready:
        ad.record("CHECK_CONFIGURED", False, "pane UI never became ready")
        ad.write_report(receipts / "paperpal_word_session.json",
                        {"aborted": True, "failure": "pane not ready"})
        print("FAILED: pane UI not ready", file=sys.stderr)
        return 1
    ad.record("CHECK_CONFIGURED", True, "pane ready")

    results: dict[str, dict] = {}
    for check in ("Grammar", "Consistency"):
        if not _click(cdp, check):
            # the pane may show a "Checks" landing first
            _click(cdp, "Checks")
            time.sleep(1)
            if not _click(cdp, check):
                results[check] = {"error": "tab not found"}
                continue
        ad.record("CHECK_RUNNING", True, check)
        print(f"[4] {check}: analysis running…")
        # wait for cards to appear and stabilize
        prev = -1
        for _ in range(60):
            time.sleep(2)
            counts = json.loads(cdp.js(JS_COUNTS))
            if counts["cards"] == prev and counts["cards"] > 0:
                break
            prev = counts["cards"]
        cards = _collect_cards(cdp)
        suggestions = []
        for c in cards:
            lines = [x.strip() for x in c.split("\n") if x.strip()]
            cat = lines[0] if lines else ""
            body = " ".join(lines[1:])
            suggestions.append({"category": cat, "text": body,
                                "class": classify_suggestion(cat, body, "")})
        by_class: dict[str, int] = {}
        for s in suggestions:
            by_class[s["class"]] = by_class.get(s["class"], 0) + 1
        results[check] = {"cards": len(suggestions), "by_class": by_class,
                          "suggestions": suggestions,
                          "categories_seen": counts.get("categories", [])}
        ad.record("CHECK_COMPLETE", True, f"{check}: {len(suggestions)} cards")
        print(f"[5] {check}: {len(suggestions)} cards, {by_class}")
        _click(cdp, "Back") or cdp.js(
            "(() => { const b = [...document.querySelectorAll('button')]"
            ".find(e => (e.getAttribute('aria-label')||'').includes('Arrow left')"
            " || (e.getAttribute('aria-label')||'').includes('Back'));"
            " if (b) b.click(); return true;})()")
        time.sleep(2)

    if not results or all("error" in r for r in results.values()):
        # never deliver an empty check report as if it were evidence —
        # the delivery binds to the staged DOCX and would pass P31 hollow
        ad.record("RESULT_CAPTURED", False, f"no check data: {results}")
        ad.write_report(receipts / "paperpal_word_session.json",
                        {"aborted": True, "failure": f"checks failed: {results}"})
        print(f"FAILED: no Paperpal check data captured: {results}",
              file=sys.stderr)
        return 1

    report = {
        "generated_at": utcnow(),
        "method": "word-addin-cdp",
        "staged_docx": docx.name,
        "staged_docx_sha256": staged_sha,
        "checks": results,
        "capture_only": True,
        "applied_changes": 0,
    }
    report_path = receipts / "paperpal_report.json"
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False),
                           encoding="utf-8")
    ad.record("RESULT_CAPTURED", True, f"{report_path.name}")

    delivered = ad.deliver(inbox, report_path, docx)
    ad.record("OUTPUT_SAVED", True, str(delivered))
    print(f"[6] delivered -> {delivered.name} (bound to {staged_sha[:12]}…)")

    closed = ad.close_word_robust(ownership)
    ad.record("PROVENANCE_WRITTEN", True, "inbox sidecar via deliver()")
    ad.record("INBOX_READY", True, delivered.name)
    ad.write_report(receipts / "paperpal_word_session.json",
                    {"finished": True, "staged_docx_sha256": staged_sha})
    print(f"[7] Word close: {closed}; session report written")
    if closed != "closed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
