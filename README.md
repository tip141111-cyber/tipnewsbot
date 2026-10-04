# tipnews

Public Telegram news digests with local Qwen summarization, topic subscriptions,
explicit source links, durable delivery state and resource-bounded RSS collection.

## Development

Python 3.12 and uv. All commands run from the repository root.

```sh
uv sync --locked
uv run tipnews check
uv run tipnews migrate
uv run tipnews collect
uv run pytest -q
uv run ruff check .
uv run mypy src
```

To run the bot, provision a private `secrets/telegram_token` file outside Git and
start `uv run tipnews run`. Do not paste credentials into commands, issues or chat.
Configuration uses `TIPNEWS_` environment variables; `.env` is not loaded implicitly.
The example file contains only variable names and non-secret defaults.

Commands: `/start`, `/stop`, `/topics`, `/digest`, `/sources`, `/weather`. A user must start the
bot to opt in. `/digest` reads the cached edition, never starts inference.
Generation starts 30 minutes before the configured daily delivery time (08:00
Europe/Moscow by default). Missed preparation retries for four hours. No model
means no generated digest; source excerpts are never silently labelled AI summaries.

Summaries must pass a Russian-language check. Non-Russian output triggers one
translation retry, then the article is omitted if the check still fails.
`uv run tipnews prepare --refresh` rebuilds today's cached edition without
resending deliveries already sent. `uv run tipnews preview` displays the edition.

Ryazan weather comes directly from Open-Meteo, not the language model. `/weather`
returns today's forecast in Europe/Moscow; `/digest` includes it before news.
Forecasts are cached for one hour and include temperatures at 08:00, 14:00 and
03:00 the following night (Europe/Moscow), precipitation
probability and maximum wind speed. Set `TIPNEWS_WEATHER_ENABLED=false` to disable.
The free Open-Meteo endpoint is intended for non-commercial use and requires
attribution, included in bot messages.

## Architecture and deployment

- [Architecture and acceptance](docs/architecture.md)
- [Decisions and pending setup](docs/decisions.md)
- [Deployment runbook](docs/operations.md)

GitHub Actions runs quality, security, migration and image smoke checks, then
publishes a commit-tagged GHCR image on `main`. Production must use its digest.
Runtime: separate application and model containers, SQLite volume, no public
application/model ports. The Ollama model must be provisioned explicitly.

Enabled feeds: GitHub Changelog, Kubernetes, SecurityLab, Bank of Russia,
BBC World, Ekaterina Schulmann's Teletype RSS, public ASTRA Telegram posts and
7info Ryazan. The politics block includes BBC, Schulmann and ASTRA; article dates
still apply, so an older Status episode is not presented as today's news.
A dedicated financial-market feed remains pending
validation; disabled topics are not offered to subscribers.
Production deployment and model quality/resource acceptance are not yet complete.
