# Task 1 brief — Record the architecture amendment

Project context: TraceCore is a Frappe v15 application. We are adding a real independent React Home at `/tracecore`, while Frappe remains the system of record and authorization boundary.

Read first:

- `CLAUDE.md`
- `docs/superpowers/plans/2026-10-24-tracecore-independent-home.md`
- `docs/superpowers/specs/2026-10-24-tracecore-independent-home-design.md`
- `.superpowers/sdd/progress.md`

Scope: implement only Task 1 from the plan.

Requirements:

1. Inspect all allocated `Amendment A-` values in `docs/architecture.md` and choose the next unused number.
2. Modify only `docs/architecture.md` and `docs/srs.md` (plus the required report file).
3. Add an architecture revision entry containing exactly this normative text:

   `TraceCore may serve an independent React application at /tracecore/*. Frappe remains the system of record and authorization boundary. /app/* remains a temporary, allowlisted administration fallback. The first deployment uses the same-origin Frappe session; AuthProvider and ApiClient isolate that choice for later separate-domain deployment.`

   Preserve the Markdown backticks around the route/code identifiers as shown in the implementation plan.
4. Update ADR-002 so its existing “Không SPA riêng” rule points to the new amendment and is no longer unconditional.
5. Add an SRS revision note stating that no FR/BRU IDs change and that the scope is only the Home entry experience.
6. Run `pre-commit run --files docs/architecture.md docs/srs.md`.
7. Self-review the diff and commit with exactly: `docs: allow independent TraceCore home`.
8. Write `.superpowers/sdd/task-1-report.md` including: summary, exact files changed, amendment number chosen, verification command and result, commit hash, and any concerns.

Do not modify application code. Do not include `.superpowers/` files in the commit.
