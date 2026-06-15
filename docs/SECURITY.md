# Security & threat model

portman is a **local developer tool**, not a network service or a hardening
control. This document is honest about what it does and does not guarantee.

## What "nothing runs without authorization" means

portman cannot *prevent* a process from binding a port. Real prevention needs
kernel-level enforcement (a firewall/LSM/EndpointSecurity hook) that portman does
not install. Instead it provides a **workflow plus a detective control**:

- **Workflow (preventive in practice):** you launch services *through* portman,
  which assigns/records the port, captures logs and owns the process.
- **Detective control:** a scanner reconciles every real listening socket against
  what portman manages and flags anything else as **unauthorized**, records it in
  the audit log, and offers a one-click **kill**.
- **Never automatic:** portman does **not** auto-kill. Killing is always an
  explicit action you take, so it can't take down a legitimate system service by
  surprise.

If you need true prevention, pair portman with an OS firewall. portman is the
visibility-and-control layer, not the enforcement layer.

## Trust boundary

- The daemon binds **`127.0.0.1` only** (loopback). It is not intended to be
  exposed to a network. There is no authentication, because the trust boundary is
  "processes running as you on this machine."
- **Do not** bind it to `0.0.0.0` or put it behind a public reverse proxy. Doing
  so would expose process control (start/kill arbitrary commands) to the network.

## Command execution

portman launches the commands you register, via the shell, **as your user**. This
is the entire point of the tool, and it is also its sharpest edge:

- Treat a registered service's `command` like anything you'd paste into your own
  terminal. A malicious `portman.yaml` is as dangerous as a malicious shell
  script — only `portman import` manifests you trust.
- Services inherit your environment plus any `env` you set, plus an injected
  `PORT`.

## Data & secrets

- All state is local: `~/.portman/` (SQLite DB + per-run logs). Nothing is sent
  anywhere; the repository never contains runtime data (`.gitignore` excludes
  `~/.portman`, `*.db`, logs).
- **Service `env` values are stored in the local SQLite DB in plaintext.** Don't
  put long-lived production secrets in a service definition; prefer your existing
  per-project `.env` mechanism, which the launched command can read itself.
- Run logs may contain whatever your service prints. They live under
  `~/.portman/logs` with your user's permissions.

## Reporting

This is a personal project. Open a GitHub issue for anything security-relevant;
do not include secrets or tokens in the report.
