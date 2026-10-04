# Operations

## Required before production

1. Complete the model RAM/quality benchmark under the proposed 800 MiB limit.
2. Choose an absolute deployment directory and create a dedicated deploy identity.
3. Install a root-owned forced-command wrapper; accept only the approved GHCR
   repository and a sha256 digest. Do not pass arbitrary SSH commands from CI.
4. Provision Telegram token file and GHCR read credentials out of band.
5. Review the model image digest and provision Qwen weights using the temporary
   `model-download.yml` override. Remove the outbound override after download.
6. Run explicit `tipnews migrate` with a consistent database backup beforehand.
7. Start the pinned image using `compose.yml`; verify actual test-chat delivery.

The root-owned wrapper and CD activation are intentionally deferred until the
server directory, credential scope and image have been established. CI can build
and publish without production SSH secrets. Never copy the interactive administrator
key into GitHub. No remote write has been performed during project scaffolding.

## Secrets

The token is a mounted file under `/run/secrets`, not an image layer or build arg.
The runtime UID 10001 must have read access to that file; do not make it world-readable.
`.gitignore` protects untracked files, `.dockerignore` independently limits build
context, Gitleaks checks content/history, tests check redaction and escaped messages.
If a real token is exposed, revoke it first; deleting a commit is not remediation.

## Health and recovery

The heartbeat checks the delivery event loop, not source quality or successful daily
publication. Watch `source_failed`, `summary_failed`, `digest_not_ready` and
`delivery_uncertain` events. Existing Prometheus/Grafana can later consume dedicated
metrics; scraping integration has not yet been installed.

Database and model volumes survive container replacement. Never run `down -v` or
global Docker prune. Back up SQLite with its backup API, not by copying the main file
while WAL writes are active. Store backups outside the VPS and rehearse restoration.
Keep the previous known-working image digest. Rollback is allowed only when schema
compatibility is verified; migrations never run implicitly on application startup.

## Production acceptance checklist

- Verified CI run and exact deployed image digest.
- Live source fetches and approved summaries in Russian.
- Scheduled message in the owner's test chat, then opt-in friends.
- Preferences and delivery history survive restart.
- 429/block/uncertain network paths do not create resend storms.
- Peak RAM/CPU and disk growth leave headroom for existing workloads.
- Successful deployment update, image rollback and backup restoration exercise.
