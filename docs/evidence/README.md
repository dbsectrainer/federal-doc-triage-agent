# Evidence Directory

This directory contains reproducible evidence from the 2026-11-01 audit.

```
docs/evidence/
├── screenshots/          # PNGs rendered from actual captured CLI output
├── test-results/         # pytest, ruff, pip-audit, smoke, demo stdout
├── build-results/        # Docker build/run/health, compile, Terraform
└── verification-report.md
```

## How the screenshots were produced

The application has no web UI. Each screenshot was rendered by
`scripts/render_evidence.py` from a log in `test-results/` or `build-results/`.
The renderer adds a title, command, capture timestamp, and terminal frame. It does
not alter, summarize, or fabricate application output.

Regenerate them:

```bash
python scripts/render_evidence.py
```

This requires Google Chrome/Chromium (`CHROME_BIN` can override the path).

## Reproduce the results

```bash
# Tests and lint
python -m pytest tests/ -v --cov=agents --cov=workflows --cov-report=term-missing
ruff check agents workflows tests lambda scripts test_local.py
python -m pip_audit -r requirements.txt
python test_local.py

# Demos
for f in samples/*.txt; do python -m agents.demo "$f"; done

# Docker
DOCKER_BUILDKIT=0 docker build -t federal-doc-triage-agent:audit .
docker run --rm federal-doc-triage-agent:audit

# Terraform
terraform fmt -check -recursive terraform
cd terraform && terraform init -backend=false && terraform validate
```

**Not reproduced here:** live AWS calls and `terraform apply` (no credentials or
authorization were available). See `verification-report.md` §7.
