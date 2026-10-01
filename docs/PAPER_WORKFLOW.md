# PAPER WORKFLOW

## Input modes (auto-detected at P01)

| Mode | Contents |
|---|---|
| CODE_ONLY | repository + experiments, no manuscript |
| DATA_ONLY | datasets/results, no manuscript |
| DRAFT_ASSISTED | existing draft (T4 — a claim map, never evidence) |
| MIXED_EVIDENCE | any combination incl. chat exports, notes, literature |

Chat/transcript ingestion (P02) is T3 provenance: visible transcripts, tool
traces, summaries. Hidden chain-of-thought is never recovered.

## The DAG at a glance

P00 doctor · P01 intake · P02 context mining · P03 research reconstruction ·
P04 evidence inventory · P05 result integrity audit · P06 literature
discovery · P07 novelty attack · P08 claim graph · P09 statistics ·
P10 reproducibility · P11/P13 figures · P12/P14 tables · P15 manuscript
architecture · P16 methods · P17 results · P18 intro/related ·
P19 discussion/limitations · P20 abstract/title · P21 citation audit ·
P22 numbers/units · P23 methods review · P24 statistics review ·
P25 adversarial review · P26 reproducibility review · P27 remediation ·
P28 scientific freeze · P29 language review · P30 semantic diff ·
P31 paperpal (manual bridge → HUMAN_REQUIRED; Automatisierung via
Word-Add-in in Umsetzung — `docs/PAPERPAL_AUTOMATION.md`) · P32 venue compliance ·
P33 clean export + secret scan · P34 independent clean rebuild ·
P35 global closure (U1–U16) · P36 human final sign-off ·
P37 optional external submission (never automatic).

Writing order is evidence-first: Methods/Results before Introduction/Abstract.

## Failure semantics

A failed node blocks only its dependents; independent branches continue.
Audit nodes PASS when the audit executed — findings carry the red and are
resolved in remediation or block closure. NOT_RUN is a first-class state and
is reported, never rounded.

## Resume

`paper-factory resume` re-enters at the first non-passing node. Human gates
(P31 delivery, P36 sign-off) resume cleanly after the human acts.
