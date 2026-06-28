<div align="center">

# 🛰️ Tracegoblins

### Stop scrolling through thousands of lines of Ansible output. *See* what broke.

[![CodeQL](https://github.com/VladoPortos/tracegoblins/actions/workflows/codeql.yml/badge.svg)](https://github.com/VladoPortos/tracegoblins/actions/workflows/codeql.yml)
[![Trivy](https://github.com/VladoPortos/tracegoblins/actions/workflows/trivy.yml/badge.svg)](https://github.com/VladoPortos/tracegoblins/actions/workflows/trivy.yml)
[![Scorecard](https://github.com/VladoPortos/tracegoblins/actions/workflows/scorecard.yml/badge.svg)](https://github.com/VladoPortos/tracegoblins/actions/workflows/scorecard.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/VladoPortos/tracegoblins/badge)](https://securityscorecards.dev/viewer/?uri=github.com/VladoPortos/tracegoblins)
[![GHCR image](https://img.shields.io/badge/ghcr.io-tracegoblins-2496ED?logo=docker&logoColor=white)](https://github.com/VladoPortos/tracegoblins/pkgs/container/tracegoblins)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2_containers-2496ED?logo=docker&logoColor=white)

A self-hosted AWX / Ansible log analyzer with lightweight team collaboration. Pull run logs
from your AWX controllers (or paste them), spot failures on a color-graded Status Map, annotate
and discuss them, and build a knowledge base that matches recurring errors to documented fixes.

It runs as two containers, the app and a Postgres database, behind your reverse proxy.

![Status Map, the hero view](pics/02-status-map.png)

</div>

---

## Why Tracegoblins?

AWX's raw stdout is a wall of text. When a 600-line playbook fails on host 7 of 12, you scroll.
Tracegoblins turns that wall into a map: every task and host, colored by status, failures
pulsing red, so you find the break fast. Then your team annotates it, talks it over, and keeps
the fix where the next person will find it.

## ✨ Features

### 🗺️ Status Map

Every play and task laid out with per-host status dots (ok · changed · skipped · failed ·
unreachable). Jump to the first failure, filter to errors only, search tasks, or scope to one
host. You get real per-task durations when the run is synced through the AWX `job_events` API.

### 🧭 Run Path Explorer

Open any run as an interactive left-to-right flow of what actually happened, rebuilt from the
AWX `job_events` tree. Drill into roles, includes, and loops, follow per-host fork branches, and
toggle never-run greying to see the branches a run skipped. The host picker shows each host's
worst status, so you can go straight to the one that failed.

- Code overlay: the playbook source at the run's exact revision, with the values the run
  actually rendered (`set_fact`, `debug`, module args) and executed / skipped / never-run lines
  colored inline. Git-link a project once and the overlay shows your real code.
- Module docs: every task links to its official Ansible module reference, and the card shows the
  module family (`apt`, `service`, `set_fact`) at a glance.
- Handler badge: a handler that was notified and fired is marked as one, so a task that ran
  because something changed doesn't read as plain ordering.
- Copy run summary: one click gives you a Markdown summary (status, per-host recap, and the
  path to the failure with error excerpts) to drop into a ticket or a KB entry.

### 🔎 Failure analysis + collaboration

Click any task for the full failure detail, the affected hosts, and the raw output in a pop-out
viewer. Annotate it (a note, tags, links) and talk it over in threaded comments with `@mentions`,
right next to the failure.

![Failure detail, hosts, annotations + discussion](pics/03-failure-drawer.png)

### 📚 Knowledge base

Promote any failure into a generalized KB entry. Tracegoblins extracts a normalized signature
(host names stripped, secrets collapsed) and `pg_trgm` fuzzy-matches future errors against it,
so the next time that error shows up its documented fix is already attached.

<div align="center">
<img src="pics/05-promote-kb.png" width="49%" alt="Promote a failure to the knowledge base" />
<img src="pics/06-knowledge-base.png" width="49%" alt="Knowledge base" />
</div>

### 🗂️ Organized per AWX instance & team

Keep My logs, Shared with me, and a Team workspace separate. In the team view you switch between
AWX sources in one click, sync on demand, and see at a glance which runs were synced and which
were uploaded.

![Dashboard, triage at a glance](pics/01-dashboard.png)

### 🔐 Security-first, internet-ready

Admin-invite-only onboarding, argon2id passwords, revocable server-side sessions, CSRF, a strict
Content-Security-Policy, encrypted AWX tokens, and a full audit log. Two-factor auth (TOTP) is
opt-in for users and enforceable for admins, with one-time recovery codes.

![Two-factor authentication](pics/04-2fa-setup.png)

### 🌗 Light & dark, self-hosted fonts

A polished IBM Plex design system with a semantic status palette, in light and dark.

![Light mode](pics/07-dashboard-light.png)

---

## 🚀 Quick start (Docker)

```bash
git clone https://github.com/VladoPortos/tracegoblins.git
cd tracegoblins

# 1) generate strong secrets into .env (needs only python3)
./bootstrap.sh

# 2a) run the prebuilt image …
docker compose pull && docker compose up -d
# 2b) … or build from source
# docker compose up --build -d

# 3) wait for health, then open the one-time setup wizard
curl --retry 20 --retry-all-errors -fsS http://localhost:8000/api/health
# open http://localhost:8000/setup   → create the first admin
```

The published image lives at `ghcr.io/vladoportos/tracegoblins` (`:latest`, or a pinned
`:vX.Y.Z` via `TG_TAG`). While the repo is private the image needs `docker login ghcr.io` first;
building from source needs nothing but Docker.

Behind a reverse proxy, keep `COOKIE_SECURE=true` and set `FORWARDED_ALLOW_IPS` to your proxy's
network. The proxy terminates TLS and owns HSTS.

### Configuration

Configuration is environment-only. [`.env.example`](.env.example) documents every option and its
default. Two settings are worth a conscious decision before you go live:

- `MFA_ADMIN_REQUIRED` (default `true`): admins are sent to 2FA enrollment and can't use the app
  until they enrol. Set it to `false` to make 2FA opt-in for admins too.
- `RETENTION_DAYS` (default `90`): see below.

### Retention

A background sweep permanently deletes AWX-synced runs (`source='awx'`) older than
`RETENTION_DAYS`, along with their tasks, raw log, annotations, comments, and shares. A run's age
is its actual job run time, or its import time when AWX didn't report one. Manually uploaded or
pasted runs are never touched. The default is 90 days; set `RETENTION_DAYS=0` to turn the sweep
off.

### Local development (hot reload)

```bash
docker compose up -d db
cd backend && uv run uvicorn app.main:app --reload --port 8000   # API  (terminal 1)
cd frontend && npm run dev                                       # SPA  (terminal 2)
```

---

## 🧰 Tech stack

| Layer | Tech |
|------|------|
| Backend | Python · FastAPI · SQLAlchemy 2.0 (async) · Alembic · Pydantic v2 · APScheduler |
| Database | PostgreSQL 16, with JSONB + `pg_trgm` / full-text |
| Frontend | Vite · React 19 · TypeScript · TanStack Query · self-hosted IBM Plex |
| Packaging | One multi-stage Docker image (Node builds the SPA, Python serves API + static) |
| Auth | argon2id · revocable sessions · CSRF · TOTP 2FA |

There's no Redis and no Celery. Background work (AWX sync, retention) runs on APScheduler with a
Postgres advisory-lock leader. Two containers, that's it.

## 🔒 Security at a glance

- argon2id password hashing; httpOnly/Secure, server-side revocable sessions
- CSRF double-submit, login rate-limiting, strict CSP and security headers
- AWX tokens encrypted at rest; TOTP secret encrypted; one-time hashed recovery codes
- full audit log; admin-invite-only (no public signup); AWX base URLs validated to http(s), with
  pagination pinned to the controller's origin so the token can't be sent off-host (AWX usually
  lives on a trusted private network, which is intended)
- supply-chain CI: CodeQL, Trivy, OpenSSF Scorecard, Dependabot, and SHA-pinned actions

It's built to sit on the internet behind a TLS-terminating reverse proxy, configured entirely
through environment variables.

---

<div align="center">
<sub>Self-hosted, two containers, and your logs stay yours.</sub>
</div>
