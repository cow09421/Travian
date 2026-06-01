# Domain docs

Single-context project with one `CONTEXT.md` at the repo root.

## Consumer rules

- **CONTEXT.md** — the one source of truth for domain language, architecture overview, and key conventions. All agents must read this before planning code changes.
- **docs/adr/** — Architectural Decision Records. Read this directory when changing a module that has an ADR. If a change contradicts a past decision, update the ADR or create a new one.
- No per-context CONTEXT.md files — this is a single-project repo.