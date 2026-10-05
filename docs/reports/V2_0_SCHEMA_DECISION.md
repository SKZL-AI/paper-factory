# V2.0 WP-II — Schema-v2-Entscheidung: v1 bleibt

Stand: 2026-10-05 · Basis: `docs/CONTRACTS.md` (WP-I, Commit daf5cf7) · Verfahren:
Prüfung auf **belegte** Contract-Probleme (realer Consumer bricht, echte Payload
lädt nicht round-trip-fähig, dokumentierte Altlast) — keine hypothetischen.

## Ergebnis

**Entscheidung: Alle Contracts bleiben auf schema_version=1. Es gibt kein
belegtes Problem, das schema_version=2 erfordern würde.**

## Geprüfte Evidenz (negativ, d.h. nichts gefunden)

1. **Gesamtes Repo nach Alt-Payloads durchsucht:** alle persistierten
   `schema_version`-Werte (fixtures, state-JSONs, docs-JSONs) sind `1`; es gibt
   keine v0-/v1.2-legacy-Payloads im Baum, die gegen das strenge v1-Modell
   laufen würden.
2. **Eingebaute Kompatibilitätspfade haben keine aktive Bruchstelle:** der
   lenient-load-Pfad für v1.2-er Receipts (ohne Timestamps) und
   `legacy_dedupe_key` (Pre-Hardening-Review-Entscheidungen) sind dokumentierte
   Kompatibilitätsanker, keine Defekte — beide sind durch Tests abgedeckt
   (`tests/test_state_store_versioning.py`, Review-Framework-Tests).
3. **Namenskollision `ExecutionReceipt` (WP-I-Befund §2/§5):** belegt durch
   Inventar, aber **kein Defekt** — keine Datei im Repo importiert beide Klassen
   gleichzeitig. Umbenennung ist ein Breaking-Rename ohne Verbraucherverbesserung;
   als TODO an schema v2 gebunden (dort fällt der Rename in dieselbe
   Versionsbump-Transaktion wie etwaige Feldänderungen).
4. **Capsule-Digest-Stabilität:** das `schema_version`-Feld liegt bewusst im
   `capsule_digest`-Payload; eine v2 ohne semantische Änderung würde sinnlos
   alle Digests kippen. Keine semantische Feldänderung ist anstehend.
5. **State-DB:** Migrations-Registry lebt (`0→1` für v1.2-er Legacy-DBs),
   `test_migrations_registered_for_every_prior_version` guardt zukünftige Bumps.

## Kriterien, die ein schema_version=2 auslösen würden

Ein Bump auf 2 wird **nur** in Betracht gezogen, wenn mindestens eines davon
empirisch eintritt:

1. **Semantische Feldsänderung** an Capsule-Digest-Feldern, WorkPackage,
   VerificationResult oder einem Receipt-Modell (neues Pflichtfeld, geänderte
   Bedeutung, entferntes Feld), die nicht als optionales Zusatzfeld ausdrückbar
   ist. Strikte Modelle (`extra="forbid"`) machen jede solche Änderung
   zwangsläufig zu einem Versionsevent.
2. **Capsule-Digest-Kollision in der Praxis** (zwei wissenschaftlich
   unterschiedliche Computationen, gleicher Digest) oder ein belegter
   Digest-Fehler — dann wächst die Digest-Feldliste, was nur über v2 ehrlich
   geht.
3. **Gemeinsame Verwendung beider ExecutionReceipt-Klassen** in einem realen
   Consumer (dann: Rename beider Klassen als Teil von v2, siehe WP-I TODO).
4. **State-DB-Schemaänderung**, die nicht als additive `MIGRATIONS[n]`-Kette
   abgebildet werden kann.
5. **Externe Consumption außerhalb dieses Repos** (drittseitige Tools lesen
   PF-Receipts/Cards), sobald dokumentiert — erst dann wird Versionsierung auch
   für Außenstehende verbindlich.

## Verfahren bei einem künftigen v2 (Vorbereitung, keine Durchführung)

- Jede v2-Modell-Datei bekommt parallel zum v1-Loader einen v1→v2-Migrationspfad
  (DB: `MIGRATIONS[1]` mit Copy-Before-Mutate; Receipts/Capsules: Loader
  akzeptiert beide Versionen, Konsum-Checks bleiben strict).
- Kein Still-Swap: alte v1-Payloads bleiben lesbar; die Immutability-Regeln des
  Projekts (Archiv statt Löschen) gelten auch für Contract-Migrationen.

**Fazit: v1 bleibt. Keine Schema-Arbeit in v2.0 — die Dokumentation (WP-I) und
diese Entscheidung sind das Deliverable.**
