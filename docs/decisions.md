# Decisions

1. Modular monolith: isolate changing integrations while respecting the VPS memory budget.
2. RSS first: no personal Telegram session or scraping arbitrary user URLs.
3. Local Ollama through an HTTP port: model implementation can move to another host.
4. SQLAlchemy + SQLite + Alembic: durable state with low operating overhead.
5. Persisted outbox, at-most-one automatic attempt after uncertain outcomes.
6. GitHub builds immutable images; the VPS does not build production artifacts.
7. Sources, prompts and migrations are reviewed code. Repository ownership controls them.
8. Private repository recommended initially; repository visibility is independent of
   whether the Telegram bot accepts public subscribers.

## Pending

- Repository remote (being created by owner).
- Telegram bot token supplied as a local/server secret file, never in chat.
- Model quality/resource benchmark and final model artifact pin.
- Final source approval for world news, Ryazan and markets; feed access != licensing.
- Production directory, restricted deploy identity and backup destination.
- Financial scope: Russia/world included provisionally, crypto excluded pending choice.
