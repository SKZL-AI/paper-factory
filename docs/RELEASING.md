# RELEASING — PAPER FACTORY

Release-Prozess ab v1.4 (Work-Pakete WP-C..WP-F, Branch `v1.4/wp-c-d-e-f-attestation`).
Historische Tags (v1.2.0, v1.3.0) bleiben **unsigned** — publizierte Tags sind
immutable, Attestation beginnt mit dem nächsten Tag-Release (verifizierter
Fakt, kein Defekt, kein Rewrite).

## 1. Tag-Release und Attestation (GitHub Artifact Attestations)

Der Workflow `.github/workflows/release-attestation.yml` läuft bei jedem
gepushten Tag `v*` (Trigger ausschließlich Tags; `workflow_dispatch` für
manuelle Kontrollläufe). Er wird **separat von der CI** geführt
(`ci.yml` unverändert) und macht genau vier Dinge:

1. Checkout des Tags, Python 3.12, `pip install build`.
2. `python -m build` → sdist (`dist/*.tar.gz`) + wheel (`dist/*.whl`).
3. `actions/attest@v4` mit `subject-path` auf beide Artefakte erzeugt
   GitHub Artifact Attestations (Signatur via GitHub OIDC/ Sigstore; offizieller
   Weg laut GitHub-Doku, verifiziert 2026-10-05).
4. Upload der Artefakte als Workflow-Artifacts (`release-dist`), damit die
   exakt attestierten Dateien herunterladbar sind.

Permissions sind minimal und job-scoped: `contents: read`,
`id-token: write`, `attestations: write` — nichts weiter.

Voraussetzung (verifiziert): Artifact Attestations sind für **public
Repositories** auf Free/Pro/Team verfügbar — `SKZL-AI/paper-factory` ist
public.

### Was der Releaser nach dem Tag-Push tut

1. Workflow-Run `Release Attestation` am Tag prüfen (grün).
2. Die attestierten Artefakte aus dem Workflow-Run oder aus dem GitHub Release
   (wenn der Releaser sie dort anhängt, ** dieselben Dateien**, nicht neu
   gebaute) herunterladen.
3. Verifikation lokal gegen das Repo:

   ```bash
   gh attestation verify paper_factory-<version>-py3-none-any.whl -R SKZL-AI/paper-factory
   gh attestation verify paper_factory-<version>.tar.gz        -R SKZL-AI/paper-factory
   ```

   Erwartung: `Verified build provenance...` mit Subject-Digest = SHA-256 der
   Datei. Erst nach erfolgreicher Verifikation werden Artefakte an ein GitHub
   Release angehängt oder zu PyPI hochgeladen.

## 2. Grenzen der Attestation — keine SLSA-Behauptung

- Die Attestation belegt **Build-Provenance**: „Dieses Artefakt wurde in
  diesem GitHub-Workflow aus diesem Repo-Tag gebaut." Sie belegt **nicht**,
  dass der Build reproduzierbar ist, und sie erteilt **kein SLSA-Level**.
- `SLSA_BUILD_REPRODUCED` wird **nicht** behauptet: laut SLSA v1.2
  Verified-Properties-Spec erfordert es den Nachweis durch **zwei oder mehr
  unabhängig betriebene Build-Plattformen**, die vom VSA-Issuer vertraut
  werden. Zwei Runs desselben GitHub-Workflows sind das nicht
  (DEEP_RESEARCH_DELTA_POST_V1_2.md §3.6, verifiziert).
- **Scientific provenance ≠ build provenance.** „Dieses Wheel stammt aus
  diesem Workflow" sagt nichts darüber aus, aus welcher Evidenz eine Zahl im
  Paper stammt. Die PF-eigene Provenance (firewall, origin receipts,
  capsule_digest) bleibt die kanonische wissenschaftliche Herkunft und wird
  durch Attestationen weder ersetzt noch abgeschwächt.

## 3. Build-Reproduzierbarkeit (WP-E, Stand 2026-10-05, lokal gemessen)

Frage: ist der lokale Wheel/sdist-Build reproduzierbar? Messung: zweimal
`python -m build` aus demselben Worktree (unveränderte Quellen), SHA-256 über
die Artefakte verglichen.

| Artefakt (v1.3.0) | Build A | Build B | identisch? |
|---|---|---|---|
| `paper_factory-1.3.0-py3-none-any.whl` | `3ce48158…2918fb81` | `d860b666…802301f22` | **NEIN** |
| `paper_factory-1.3.0.tar.gz` | `e72db6e7…0c90b11b5d` | `1d2fb944…c13db19ad2b` | **NEIN** |

Root-Cause (instrumentiert, nicht spekuliert): die Nutzdaten sind
**byte-identisch** (aller 117 Wheel-Member und aller 183 sdist-Member
inhaltlich gleich), aber Wheel-Zip-`date_time`-Einträge und sdist-Tar-`mtime`-
Werte tragen den Build-Zeitpunkt. Standard-`setuptools`/`wheel` setzen keine
reproduzierbaren Zeitstempel.

**Ehrliches Verdikt: PF-Builds sind aktuell NICHT bit-reproduzierbar.**
Es wird keine Reproduced-Behauptung gemacht; `SLSA_BUILD_REPRODUCED` bleibt
unbelegt (s. §2). Eine Reproduzierbarkeits-Runde (SOURCE_DATE_EPOCH,
normalisierte Archive) ist ein mögliches Folge-Paket — nur mit eigenem
Messnachweis.

### Artefakt-Hygiene (mitgemessen)

- Wheel: 117 Member, ausschließlich Package-Code; kein `.env`, kein Token,
  kein Zustandsverzeichnis. (`paper_factory/release/secrets.py` ist der
  eigene Secret-Scanner des Release-Gates, kein Geheimnis.)
- sdist: 183 Member, enthält zusätzlich `tests/`, `LICENSE`, `README.md`,
  `pyproject.toml` — Standard-Set, nichts Privates.
- Versions-String: `1.3.0` korrekt in beiden Artefakten.

## 4. Checkliste für das nächste Release (v1.4.0+)

1. `pyproject.toml`-`version` auf das Release setzen und mit dem
   CHANGELOG-Eintrag abstimmen (Reviewer MAJOR-1 A, v1.4-Fixloop: der
   CHANGELOG trug 1.4.0, `pyproject.toml` noch 1.3.0 — die gebauten
   Artefakte nehmen diese Versionsnummer, ein Mismatch ist ein
   Release-Gate-Befund). CHANGELOG-Eintrag und Suite grün
   (`python -m pytest tests -q`).
2. Tag setzen (`v<version>`) und pushen → `Release Attestation` läuft.
3. Beide Artefakte mit `gh attestation verify` verifizieren (§1).
4. Erst dann Release anlegen / Artefakte anhängen / PyPI.
5. Kein SLSA-Claim in Release-Notes; Build-Provenance und Scientific
   Provenance getrennt ausweisen (§2).

### 4a. Attestation-Workflow: eingegangene Restrisiken (dokumentiert)

- **Actions sind Versions-gepinnt, nicht SHA-gepinnt**
  (`actions/checkout@v4`, `actions/setup-python@v5`,
  `actions/attest@v4`, `actions/upload-artifact@v4`). Ein kompromittiertes
  oder umbesetztes Tag einer Action könnte den Build-Schritt korrumpieren,
  ohne dass sich der Workflow-Text ändert. Bekanntes, akzeptiertes
  Rest-Risiko für v1.4.0 (Review-Befund MINOR): Versions-Pins sind der
  übliche Mittelweg zwischen `@main` und SHA-Pinning; die Upgrade-Disziplin
  (Renovate/Dependabot-Strategie mit getesteten Bump-PRs) ist als
  Follow-up geplant, bis dahin erfolgen Action-Upgrades manuell und nur
  mit Blick auf den Workflow-Run-Verlauf.
- **`workflow_dispatch`-Läufe sind Nicht-Release-Attestationen.** Der
  Workflow ist auf Tag-Push (`v*`) ausgerichtet; der manuelle
  `workflow_dispatch`-Pfad dient Kontrollläufen. Der Run-Name kennzeichnet
  Dispatch-Läufe ausdrücklich als **NON-RELEASE** (sichtbar in der
  GitHub-Run-Liste), und nur Tag-Trigger gehören zum Release-Verfahren
  (§1). Beim Verifizieren (`gh attestation verify`) auf den Tag-Run
  achten, nicht auf einen Dispatch-Kontrolllauf.
