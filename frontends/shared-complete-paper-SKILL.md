---
name: complete-paper
description: Run or resume the harness-neutral evidence-first Paper Factory pipeline.
compatibility: Requires the `paper-factory` CLI installed in the current environment.
---

# Complete Paper

Use the deterministic Paper Factory core.

For a normal run:

```bash
paper-factory complete
```

Pass user-supplied arguments through unchanged.

Examples:

```bash
paper-factory complete --resume
paper-factory complete --dry-run
paper-factory complete --target arxiv
```

Do not substitute an in-chat paper-writing workflow for the core.
Read and report the CLI status. If a human-only gate is reached, surface that gate.
