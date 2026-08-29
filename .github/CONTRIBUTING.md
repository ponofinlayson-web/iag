# Contributing to IAG

Thanks for your interest in making IAG better.

## Read this first

- [REQUIREMENTS.md](../REQUIREMENTS.md) and [ARCHITECTURE.md](../ARCHITECTURE.md) are
  the frozen domain contracts. If your change touches behavior described there,
  update the spec in the same PR.
- [README.md](../README.md) has the Docker quickstart.

## Development setup

The fastest loop is Docker (see the README quickstart). For backend-only work:

```bash
cd backend
uv sync
```

## Running the tests

The full backend suite runs without any external services:

```bash
cd backend
IAG_ENV=test IAG_SECRET_KEY=test-secret-key-0123456789abcdef0123456789abcdef uv run pytest tests/ -x -q
```

CI runs this exact command on every PR (`.github/workflows/ci.yml`). If it passes
locally it should pass in CI.

## Pull requests

1. Branch from `main` (`feat/...`, `fix:...`, `docs/...`).
2. Keep PRs small and single-purpose.
3. Add or update tests for any behavior change. Bug fixes should include a
   test that fails without the fix.
4. Fill in the PR template. If any part of the change was generated with AI
   assistance, tick the AI-assistance box - this is a disclosure convention
   for this project, not a judgment.

## Commit style

Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`).
The changelog is assembled from these.

## Reporting vulnerabilities

Do **not** open a public issue for security problems - see [SECURITY.md](SECURITY.md).
