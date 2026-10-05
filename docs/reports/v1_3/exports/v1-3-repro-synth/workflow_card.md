# Workflow Card — v1-3-repro-synth-01

> ⚠️ DERIVED SUMMARY: built exclusively from canonical machine evidence (ReproductionCapsule + ExecutionReceipts). This card is never a source of truth and never a gate input — PF-internal provenance and receipts remain authoritative.

## Capsule

- **capsule_id:** `v1-3-repro-synth-01`
- **capsule_digest:** `6b1efffda4f6f85ffbfb09dfeb3677440d45972862012af0f51fab145251eee3`
- **command:** `python3 pilot_compute.py`
- **cwd:** `.`
- **producer:** pf_native/paper-factory 1.3.0-dev
- **provenance_refs:** pilots/v1-3-repro-synth/

## Environment

- **python:** 3.13.5 · **platform:** linux-x86_64

## Inputs

- `input.csv` — sha256 `a487603cefcf181583cb697952dcd3eaf71632ec2a31c9f541055e9904689a48`

## Configuration

_none declared_

## Code

- `pilot_compute.py` — sha256 `e0b2b4b8838bcf298dfe6e578c7b7a3ac37496d77b267a272442539bec4e6b83`

## Expected outputs

- `summary.json`
- `table.txt`

## Runs

- `exec-3551584deb734cb8b9d5ffc80c35f1d1` — **completed** (exit 0) via pf_native/local-reproduction-runner 0.1.0, 0.017s
  - output `summary.json` — sha256 `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2`
  - output `table.txt` — sha256 `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de`
- `exec-07763ce472ae4139bfa9ba112ac61dd5` — **completed** (exit 0) via pf_native/local-reproduction-runner 0.1.0, 0.018s
  - output `summary.json` — sha256 `8f76c7d9d07d070ba3aa3fffa058a4d65212fc9a97915596587531ce1d4ec5b2`
  - output `table.txt` — sha256 `01e71442cf89bf465d78c3c972f8c969825b2dd62db8546e5e7e972d98a483de`

## Reproduction status

- **executions:** 2
- **comparison:** none (fewer than two executions or not compared)

## Limitations

- none declared in the capsule evidence
