# Contributing to Aegis

## Branch Strategy
- Create feature branches from `main`.
- Naming convention: `feature/phase-X-description` (e.g., `feature/phase-1-monitoring`).

## Commit Conventions
We follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation updates
- `test:` for adding or updating tests
- `refactor:` for code refactoring
- `ci:` for CI/CD pipeline changes

## PR Expectations
- Meaningful PR description.
- All tests must pass (`make test`).
- Link the PR to a relevant issue or phase.
- Keep changes focused (no unrelated changes).

## Testing Requirements
- All new code must be accompanied by tests.
- Run `make test` before opening a PR.

## Code Review
- At least 1 approval is required to merge.
- No self-merging.

## Documentation
- If you change interfaces or architecture, update the relevant documentation in `docs/`.

## Development Setup
- Follow the instructions in `README.md` to set up your local development environment.
