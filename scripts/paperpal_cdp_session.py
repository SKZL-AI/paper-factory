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


def _find_cdp_port() -> int:
    """The WebView2 user-data dir carries DevToolsActivePort (port + path)."""
    base = (r"C:\Users\SAI\AppData\Local\Microsoft\Office\16.0\Wef")
    out = _ps(f'Get-ChildItem -Recurse -Filter DevToolsActivePort "{base}" '
              '| Select-Object -ExpandProperty FullName')
    for line in out.splitlines():
        p = line.strip()
        if not p:
            continue
        content = win_to_wsl(p).read_text().splitlines()
        return int(content[0].strip())
    raise RuntimeError("no DevToolsActivePort found — is Word running with "
                       "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS?")


def _click(cdp: CDP, text: str) -> bool:
    return bool(cdp.js(
        "(() => { const b = [...document.querySelectorAll('button, [role=button]')]"
        f".find(e => e.textContent.trim() === {json.dumps(text)});"
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

    # open Word headless-friendly with WebView2 CDP enabled
    _ps("$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port=0';"
        " $w = New-Object -ComObject Word.Application; $w.Visible = $true;"
        f" $w.Documents.Open('{win}') | Out-Null;"
        " $w.ActiveWindow.WindowState = 2", timeout=120)  # 2 = minimize
    ad.record("WORD_OPEN", True, win)
    print("[2] Word opened (minimized) — waiting for Paperpal pane")

    port = None
    for _ in range(30):
        try:
            port = _find_cdp_port()
            break
        except Exception:
            time.sleep(2)
    if port is None:
        # pane not open yet: click the Paperpal ribbon via UIA, retry
        print("[2b] no CDP port — opening Paperpal pane via UIA")
        subprocess.run([sys.executable,
                        str(Path(__file__).with_name("run_paperpal_word.py")),
                        "--root", str(root), "uia-click", "Paperpal"],
                       capture_output=True, timeout=120)
        subprocess.run([sys.executable,
                        str(Path(__file__).with_name("run_paperpal_word.py")),
                        "--root", str(root), "uia-click", "Open Paperpal"],
                       capture_output=True, timeout=120)
        for _ in range(30):
            try:
                port = _find_cdp_port()
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

    _ps("$w = Get-Process WINWORD -ErrorAction SilentlyContinue;"
        " if ($w) { $word = [Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application');"
        " $word.DisplayAlerts = 0; $word.Quit() }", timeout=60)
    ad.record("PROVENANCE_WRITTEN", True, "inbox sidecar via deliver()")
    ad.record("INBOX_READY", True, delivered.name)
    ad.write_report(receipts / "paperpal_word_session.json",
                    {"finished": True, "staged_docx_sha256": staged_sha})
    print("[7] Word closed, session report written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
