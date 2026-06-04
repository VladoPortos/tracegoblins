# Security Policy

## Supported versions

Tracegoblins is distributed as a rolling release. Security fixes land on the
`main` branch and are published to the `latest` container image on GHCR. Always
run the most recent image; older tags do not receive backported fixes.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/VladoPortos/tracegoblins/security/advisories/new)
("Report a vulnerability" under the repository's **Security** tab). This keeps
the details confidential until a fix is available.

When reporting, please include:

- A description of the issue and its impact.
- Steps to reproduce (proof-of-concept, affected endpoint/component, config).
- The image tag or commit you tested against.

You can expect an initial acknowledgement within a few days. Once a fix is
released, we are happy to credit you in the advisory unless you prefer to
remain anonymous.

## Scope & hardening notes

Tracegoblins is designed to run **behind a TLS-terminating reverse proxy** and
ships security-first defaults: argon2id password hashing, server-side revocable
sessions (httpOnly/Secure cookies), CSRF protection, login rate-limiting,
encrypted AWX tokens, an audit log, and optional TOTP two-factor auth. Deploying
the app directly on the public internet without TLS termination is unsupported.

Secrets (session keys, token-encryption key, DB credentials) are provided via
environment only — never commit real secrets to a fork or deployment repo.
