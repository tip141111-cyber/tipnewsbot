# Gemini migration

The default provider remains Ollama so deploying this revision without a Gemini key
does not disable the existing bot. Gemini is explicitly selected by
`TIPNEWS_LLM_PROVIDER=gemini`. No API calls happen when running tests or `check`.

## Runtime configuration

| Setting | Default / purpose |
| --- | --- |
| `TIPNEWS_LLM_PROVIDER` | `ollama`; choose `gemini` explicitly |
| `TIPNEWS_GEMINI_MODEL` | `gemini-2.5-flash`; verify availability before activation |
| `TIPNEWS_GEMINI_API_KEY` | Secret, supplied out of band |
| `TIPNEWS_GEMINI_API_KEY_FILE` | Optional secret file, takes precedence over the variable |
| `TIPNEWS_GEMINI_MAX_OUTPUT_TOKENS` | 512, bounded between 128 and 2048 |
| `TIPNEWS_GEMINI_DAILY_REQUEST_LIMIT` | 100 API attempts per UTC day, persisted in SQLite |
| `TIPNEWS_GEMINI_TIMEOUT_SECONDS` | 45 seconds per request |

For local Python execution export the variables in the process environment; `.env`
is not loaded automatically. The Gemini Compose file explicitly maps values from
Compose interpolation into the application container. Use an explicit `--env-file`
with a private operator-managed file so its location is unambiguous. Never paste its
contents into chat or logs. Do not print expanded `docker compose config`; validation
must use `config --quiet`. Environment-based keys are visible to Docker administrators;
the application also supports a mounted key file for deployments that require it.

Only bounded public article material and the editorial prompt are sent to Google.
Subscriber identifiers, topic preferences and Telegram credentials are not sent.
Keys use the `x-goog-api-key` header, never a URL query parameter. Automatic redirects
are disabled. Logs exclude response bodies and redact common Gemini key forms.

## Generation and limits

One request summarizes the title (up to 300 characters) and feed material (up to
6000 characters). The prompt asks for natural Russian prose, 1–2 factual sentences,
preferably within 320 characters. Existing source attribution and numeric checks
remain; validation does not prove factual accuracy. Russian-language failure allows
one retry. Blocked, truncated, malformed, linked or numerically inconsistent outputs
are omitted. There is no implicit fallback to another provider.

Each HTTP request has at most three attempts for transport errors, HTTP 429 and
selected transient 5xx errors. Short numeric Retry-After values are honored; a long
or date-valued delay defers work to a later preparation cycle. Authentication errors
are not retried inside the request. Every attempt consumes the persisted daily
request allowance, including timeouts. Reported input/output/thinking token usage
is recorded in `inference_usage` and logged without article text. Unreported usage
after a timeout cannot be measured locally. The local UTC day is independent of
Google's quota reset schedule. This is a request cap, not a guaranteed currency cap;
configure billing controls with the provider as well.

Gemini 2.5 Flash models use thinkingBudget=0. Other model families use their own
defaults; review output token budgets, pricing and quality before changing the model.
Cache versions include provider, model, prompt, generation settings and input rules.

## Activation and rollback

1. Confirm the account, server and intended audience meet Google's current region
   and service requirements; confirm the selected model and billing limits.
2. Review the CI result and pin the image digest. Take and verify a consistent SQLite
   backup before running migrations. Migration 0002 only adds inference usage; it
   does not rewrite subscribers, digests or delivery history.
3. Provision the Gemini key in the private environment file or mount a secret file.
   Run explicit migrations against the intended volume; startup does not migrate.
4. Test generation against a separate test database with no real subscribers. Compare
   Russian and English inputs, numbers, attributed statements, politics, long texts,
   refusal rates, latency and reported token usage. Review complete Telegram-length
   editions, not just individual summaries.
5. `deploy/compose.gemini.yml` is a standalone alternative to `compose.yml`, not an
   override to merge with it. Preserve the existing Compose project identity and
   `app_data` volume. Confirm actual server paths and project naming before switching.
6. Start the approved image using the Gemini configuration and verify commands,
   preparation, weather and one complete delivery cycle. The old Ollama container
   may remain as an orphan after switching configurations; stop that specific service
   only after verification. Never delete the model or database volumes as part of
   switching providers. Stopping Ollama is what releases its runtime RAM.
7. For image/provider rollback retain the Ollama Compose file, model volume and last
   working image. The additive usage table can remain when the older image runs;
   do not run a destructive schema downgrade. Keep delivery history intact.

`prepare --refresh` now actually replaces matching article summaries and updates only
pending deliveries. Sent/uncertain deliveries are not requeued. Existing valid text
is retained if replacement generation fails. Before scheduled delivery, preparation
retries every 15 minutes and reuses successful summaries to recover partial editions.
Startup and catch-up generation use the previous calendar day. A late catch-up
edition is due immediately on its own date, not the following day.

The existing GitHub workflow tests and publishes GHCR images. It does not contain a
server deployment step. Verify the separate server updater before assuming a push
has activated Gemini. Health checks only prove the event loop is alive, not successful
generation or delivery.

## Provider references

- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/available-regions
- https://ai.google.dev/gemini-api/terms
