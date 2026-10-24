# TraceCore Independent Home — Design

**Date:** 2026-10-24  
**Status:** Approved by user on 2026-10-24; proposed architecture amendment, not yet implemented  
**Scope:** Replace the default Frappe Desk landing page with an independent TraceCore Home. This design does not rebuild the 21 supplied operational screens.

## 1. Goal

Create a TraceCore-owned Home experience that becomes the first page after login. It must preserve the visual language shown in `TraceCore_UI_Screenshots.zip` while removing the visible Frappe Desk shell from the normal entry experience.

The Home is a role-personalized hybrid dashboard:

- urgent work and warnings first;
- a small set of relevant metrics;
- shortcuts based on server-authorized capabilities;
- links to custom TraceCore screens when available;
- controlled fallback links to existing Frappe Desk screens during migration.

The initial deployment uses the same domain and the existing Frappe session. The frontend must be structured so it can later move to a separate domain without rewriting UI components.

## 2. Non-goals

- Rebuild all screenshots or all WEB/STN/PDA/DEPT screens in this feature.
- Replace Frappe as the data, permission, workflow, audit, job, or business-rule backend.
- Reimplement permission or lifecycle rules in the browser.
- Remove Frappe Desk before every fallback function has a custom replacement.
- Add real-time streaming metrics in the first release.

## 3. Architecture amendment

This design conflicts with the current ADR-002 rule that disallows a separate SPA. Before implementation, add an architecture amendment that permits:

1. an independent TraceCore SPA for `/tracecore/*`;
2. Frappe as the backend and temporary administration fallback;
3. same-domain cookie-session authentication initially;
4. a later separate-domain deployment through replaceable auth and API adapters.

The amendment does not authorize moving business logic into the frontend.

## 4. System boundary

### 4.1 Frontend

Create a React + TypeScript + Vite application in the standalone source directory `frontend/`.

The application owns:

- the TraceCore application shell;
- client-side routing under `/tracecore/*`;
- Home presentation and role-personalized composition;
- navigation and safe route resolution;
- loading, empty, error, stale, and offline presentation;
- a replaceable authentication adapter;
- a single API client.

It must not import Frappe Desk components, Desk CSS, Desk router, or Desk page lifecycle APIs.

### 4.2 Backend

Frappe continues to own:

- DocTypes and the database;
- roles, permissions, and capability decisions;
- workflows and lifecycle transitions;
- audit logging;
- business validation;
- background jobs;
- authentication and session management in the first deployment.

### 4.3 Routes

| Route | Owner | Purpose |
| --- | --- | --- |
| `/tracecore` and `/tracecore/home` | TraceCore SPA | Personalized Home |
| `/tracecore/search` | TraceCore SPA | Global scan/search |
| `/tracecore/station/*` | TraceCore SPA or migration adapter | Custom operational screens |
| `/app/*` | Frappe Desk | Temporary fallback and System Manager administration |

All users land on `/tracecore` after login. System Manager receives an explicit **Frappe Admin** navigation item. Other Frappe fallback links appear only when both the server capability and the frontend allowlist permit them.

## 5. Authentication and API isolation

The first deployment runs on the same domain as Frappe and uses the existing session cookie and CSRF protections.

UI components access authentication only through `AuthProvider` and server calls only through `ApiClient`. These adapters must isolate cookie/session assumptions so a future token-based deployment at `app.tracecore.vn` does not require component rewrites.

On session expiry, the app redirects to login and preserves the intended safe SPA route. Logout calls the Frappe logout endpoint and clears all frontend caches containing user-specific data.

## 6. Home information architecture

The Home uses one component hierarchy for every role. The backend varies the permitted content; the frontend does not maintain separate role-specific Home implementations.

### 6.1 Application shell

- Persistent left sidebar on desktop.
- User, role, department, active shift/station, connection state, and logout.
- Navigation groups generated from server capabilities.
- On PDA/mobile, use an explicit open/close menu rather than an icon-only collapsed rail.
- No Frappe toolbar, module list, Desk breadcrumb, or Desk chrome.

### 6.2 Header

- Greeting, work date, current role, shift, and station context.
- Global scan/search for Set ID, Cycle ID, load/batch code, and equipment code.
- Search results route only to resources the user may read.

### 6.3 Attention queue

This is the first content block. It contains only actionable items the current user may handle, such as:

- par override requests;
- loads waiting for release;
- unconfirmed recalls;
- blocked equipment or missing daily tests;
- expiring competencies or certificates.

Every item contains a severity label, human-readable reason, and direct action. Severity is never conveyed by color alone.

### 6.4 Metrics

Show four to six metrics at most.

- R01/R02: operational and approval metrics.
- Technicians: station workload, queue, and blocking conditions.
- Department users: sets at department, sets in reprocessing, expiring packs, and recalls.
- System Manager: operational health plus the administration entry point.

Home is not a replacement for full reports.

### 6.5 Shortcuts

Show no more than eight high-value shortcuts. Prefer, in order:

1. continue the current station/session;
2. global scan/search;
3. assigned or waiting work;
4. frequently used permitted functions.

Each shortcut resolves through a frontend route registry. The server returns a `route_key`, not an arbitrary URL. A route registry entry declares whether the destination is an SPA route or an allowlisted Frappe fallback.

### 6.6 Recent records

Recent records are deferred from the first release to iteration 3. Show five to ten records, recheck read permission on the server, and exclude patient identifiers and other sensitive values.

## 7. Home context API

Add one aggregate read endpoint:

```text
GET /api/method/tracecore.v1.home.context
```

The response contract contains:

```json
{
  "ok": true,
  "user": {},
  "capabilities": [],
  "navigation": [],
  "attention": [],
  "metrics": [],
  "shortcuts": [],
  "recent": [],
  "system": {},
  "etag": "..."
}
```

Requirements:

- calculate permissions and capabilities on the server;
- use stable semantic keys rather than translated labels as identifiers;
- return translated user-facing text or stable translation keys consistently;
- never return arbitrary executable URLs;
- omit sensitive patient data;
- support ETag/not-modified semantics;
- include frontend/API compatibility information in `system`;
- keep query count bounded and avoid one query per card or shortcut.

Frontend filtering is only a presentation aid. Every destination API checks permission again.

## 8. Visual language

Use the supplied screenshot set as the visual reference:

- white sidebar and light neutral application background;
- dark blue headings, table headers, and primary structural accents;
- flat cards with thin blue-gray borders;
- red/orange/green states with text labels or symbols;
- readable typography and identifier-specific monospace treatment;
- no decorative backgrounds, gradients, or Frappe visual chrome.

Existing `docs/tokens.json` remains the machine-readable token source unless the amendment explicitly changes a token. The Home may compose new components but must not create an unrelated design system.

## 9. Loading, error, stale, and offline behavior

- **Loading:** render a Home-shaped skeleton, not a full-page spinner.
- **Empty:** show a positive empty message and omit empty metric/action containers.
- **Permission changed:** refresh context; if access was revoked, show an inline explanation and return Home.
- **Session expired:** redirect to login without exposing a technical error.
- **API unavailable:** render the shell and the last cached context read-only, clearly marked with its last-updated time.
- **Frontend/API mismatch:** require a controlled reload before allowing business actions.
- **Fallback link failure:** keep Home open and show an inline retry action.
- **Offline:** permit cached Home reading and navigation only to explicitly offline-capable PWA screens; disable server-required actions with a reason.

Client logs and telemetry must not contain patient identifiers or sensitive payloads. Include request ID, route key, and server error code where available.

## 10. Performance and accessibility

- Target useful Home content within one to two seconds on the hospital intranet.
- Metrics may refresh on load and at a bounded interval; real-time streaming is out of scope.
- Support desktop 1366×768 and PDA 412×915.
- Preserve keyboard operation, visible focus, semantic headings, and accessible names.
- Do not communicate status through color alone.
- Respect reduced-motion preferences.

## 11. Delivery iterations

### Iteration 1 — Independent foundation

- React/TypeScript/Vite application.
- Router, `ApiClient`, `AuthProvider`, tokens, and application shell.
- Serve `/tracecore/*` through the existing deployment.
- Login redirect and System Manager **Frappe Admin** entry.
- Static/sample Home composition only.

### Iteration 2 — Personalized Home

- `tracecore.v1.home.context`.
- Server-derived navigation, capabilities, attention, metrics, and shortcuts.
- Configurations for R01/R02, technicians, department users, and System Manager.
- Allowlisted Frappe fallbacks.

### Iteration 3 — Search and existing-screen integration

- Global scan/search.
- Safe routing for Set ID, Cycle ID, batch/load, and equipment codes.
- Adapters to existing custom TraceCore screens.
- Permission-checked recent records on Home.
- Unified loading/error/offline states.

### Iteration 4 — Hardening and PWA behavior

- Shell and last-context cache.
- Frontend/API version handshake.
- Privacy-safe telemetry.
- Responsive and accessibility validation.

### Iteration 5 — Gradual migration from Desk

- Measure which fallback shortcuts remain most used.
- Migrate those screens through separate feature designs and plans.
- Restrict `/app` to System Manager when no business workflow depends on Desk.

## 12. Verification

Required test layers:

- frontend unit tests for route registry, capability presentation, auth adapter, and API adapter;
- backend contract tests for `home.context`;
- backend permission tests for every supported role group;
- component tests for loading, empty, error, stale, and offline states;
- Playwright at 1366×768 and 412×915;
- E2E: login → Home redirect → SPA destination → Frappe fallback → logout;
- direct-route refresh, browser back/forward, expired session, revoked permission, and frontend/API version mismatch;
- visual regression against the approved TraceCore screenshot language.

## 13. Rollout and rollback

Guard the redirect and new Home with a site-level feature flag.

Rollout order:

1. developers and System Manager;
2. R01/R02 pilot users;
3. technicians by station;
4. department users;
5. all eligible users.

Rollback disables the redirect/feature flag and returns users to the existing Frappe landing page. It must not require database rollback because the Home feature introduces no new source-of-truth business records.

## 14. Decisions recorded

- Scope is the Home replacement, not all 21 operational screens.
- Use a single role-personalized Home.
- Use a hybrid dashboard and launcher layout.
- Use React + TypeScript + Vite.
- Deploy on the same domain with the Frappe session first.
- Keep the frontend independent of the Frappe Desk runtime.
- Permit phased, allowlisted links to Frappe functions.
- Redirect every user to TraceCore Home; expose Frappe Admin explicitly to System Manager.
