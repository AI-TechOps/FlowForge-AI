# Contributing to FlowForge-AI

## Workflow

Direct pushes to `main` are blocked. All changes land through pull requests:

1. **Sync and branch from `main`:**

   ```bash
   git checkout main && git pull origin main
   git checkout -b feat/short-description   # or fix/, docs/, chore/, refactor/
   ```

2. **Make your changes.** Keep PRs focused — one logical change per PR.

3. **Verify locally before pushing:**

   ```bash
   ruff check . && ruff format --check .
   pytest
   ```

4. **Push and open a PR** against `main`. Fill in the PR template.

5. **Review requirements** (enforced by branch protection):
   - 2 approving reviews, including code owners (see `.github/CODEOWNERS`)
   - All CI checks green: `lint`, `test`, `secret-scan`
   - Branch up to date with `main` before merging

## Branch naming

| Prefix      | Use for                          |
| ----------- | -------------------------------- |
| `feat/`     | New features                     |
| `fix/`      | Bug fixes                        |
| `docs/`     | Documentation only               |
| `refactor/` | Code changes with no behavior change |
| `chore/`    | Tooling, CI, dependencies        |

## Commit messages

Use present-tense, imperative subject lines ("Add ticket triage agent", not
"Added..."). Explain *why* in the body when the change isn't self-evident.

## Secrets

Never commit API keys, tokens, `.env` files, or credentials — the repo will be
public. CI runs a secret scan on every PR; `.gitignore` covers the common
cases, but the scan is a backstop, not a license to be careless. Use
environment variables and document required ones in the README.
