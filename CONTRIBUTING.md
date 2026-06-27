# Contributing

Thank you for your interest in contributing. This project is a clinical AI tool — contributions that improve accuracy, safety, and usability are especially welcome.

## Ground Rules

- **Patient safety first.** Never introduce changes that could produce misleading clinical output without appropriate safeguards and reviewer signoff.
- Be respectful. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- Open an issue before starting large changes so we can align on direction.

## Getting Started

1. Fork the repository and clone your fork.
2. Follow the [Quick Start](README.md#quick-start) setup in the README.
3. Create a branch: `git checkout -b feat/your-feature` or `fix/your-bug`.
4. Make your changes, write tests where applicable.
5. Open a Pull Request against `main`.

## Development Setup

See [README.md](README.md) for full local dev instructions. Short version:

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8001

# Frontend
cd frontend && npm install && npm run dev
```

## Code Style

**Backend (Python):**
- Ruff for linting and formatting (`ruff check . && ruff format .`)
- Type hints required for all public functions
- Pydantic models for all request/response schemas

**Frontend (TypeScript):**
- ESLint + Prettier (`npm run lint`)
- No `any` types unless strictly unavoidable
- Tailwind for all styling — no inline CSS objects except for dynamic values

## Pull Request Checklist

- [ ] `npx tsc --noEmit` passes (frontend)
- [ ] `ruff check .` passes (backend)
- [ ] No secrets, API keys, or personal data in any committed file
- [ ] `.env` files are not committed (only `.env.example`)
- [ ] PR description explains what changed and why
- [ ] Clinical changes include a note on how the change was validated

## Reporting Bugs

Open a GitHub Issue. Include:
- Steps to reproduce
- Expected vs actual behaviour
- Browser / OS / Python / Node versions

## Security Issues

Do **not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md).
