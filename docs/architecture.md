# tipnews architecture

## Scope

Public Russian-language Telegram bot, opt-in topic subscriptions, one short daily
digest with source article links. Sources are selected by the operator. The model
only summarizes supplied text; it does not verify truth or invent analysis.
An RSS excerpt is not presented as a summary of an unread full article.

## Boundaries

Modular monolith: domain values and selection policies; application use cases;
ports for sources, storage, inference and delivery; adapters for RSS, SQLAlchemy,
Ollama and Telegram. One active application instance initially. Ollama runs in a
separate container with no published port. No Redis, Celery or Kubernetes required.

Sources -> bounded RSS fetch -> normalized articles -> SQL database -> bounded
daily selection -> sequential summarization -> immutable digest -> durable outbox.
User commands only read cached digests and change subscriptions.

SQLite WAL and explicit Alembic migrations initially. Repository methods own
transactions. No session is shared between asynchronous tasks. PostgreSQL and
worker separation require a migration and concurrency tests, not just a URL edit.

## Failure semantics

Digest date is unique in the configured timezone. Draft generation resumes using
cached per-article summaries. Publishing and outbox insertion are one transaction.
Deliveries are claimed before network I/O. Uncertain network outcomes and in-flight
rows after restart become `uncertain`, avoiding automatic duplicate delivery at the
cost of possible missed delivery. Exactly-once Telegram delivery is not promised.
Telegram 429 schedules a retry; blocked chats are paused. Ordinary retries are bounded.
Feed errors are isolated and do not erase previously collected news. No fabricated
fallback summary: unavailable inference prevents publication and is visible in logs.

## Resource budget

Observed server: Ubuntu 26.04 x86_64, 4 vCPU, 1960 MiB RAM, no swap, about 13 GiB disk.
2026-10-04 audit: 1230 MiB available, sampled 24h minimum about 1180 MiB; no OOM in
that window. Existing music bot, VPN and monitoring must remain operational.
Qwen3 0.6B Q4 is provisional until quality and peak-RAM measurements pass. Single
inference request, short bounded input, no thinking, unload after idle. Never
download weights or build images as part of application startup.

## Security boundaries

Tokens are runtime files, excluded from Git and Docker context. Only approved static
HTTPS feeds are fetched. No user-submitted URL fetches. Redirects are validated before
following them. Article markup is stripped; Telegram HTML is escaped. Model output
cannot execute commands, change recipients, or supply the source link.
LLM responses are length/structure checked, but that is not factual verification.
Log formatter redacts token-shaped values including tracebacks; HTTP logs are limited.

## Delivery and operations

GitHub-hosted CI -> tested GHCR image -> deployment by immutable digest.
No production credentials in PR workflows, no production self-hosted runner.
Deployment key must be separate and limited to a root-owned fixed deployment wrapper;
membership of docker group alone is NOT least privilege. Existing SSH identity is
for interactive administration, not for storing in Actions.
Bootstrap, migrations, deployment and rollback are separate operations. Database
backup must be consistent and restore-tested. Image rollback requires compatible schema.
Use Europe/Moscow explicitly; the host currently uses Europe/Prague.

## Acceptance

- CI: lint, types, tests, secret scan, dependency audit, image smoke/security checks.
- Real source collection and measured local-model summarization.
- Opt-in user receives a scheduled digest containing working original links.
- Restart preserves preferences and delivery state.
- CD upgrades the chosen image; rollback and DB restore are rehearsed.
- Existing services remain healthy during the model workload.

Production acceptance remains pending until all checks are observed on the server.
