# Operations guide

## Application

FastAPI serves the API and the compiled web client. Install the locked Python
requirements, then run `uvicorn api:app --host 0.0.0.0 --port "$PORT"`.
The deployment branch is `deploy-cashshifts`; verify the hosting configuration
before pushing changes to it because automatic deployment may be enabled.

## Web assets

`web/dist` is required at runtime and intentionally versioned. When changing
frontend code, run `npm ci` and `npm run build` in `web`, then include the
resulting assets in the reviewed change. Do not remove `web/dist` as a cache.
The screenshots in `docs/screenshots` are demo assets used by the help pages.

## Configuration and data

Use `.env.example` as a list of settings, not as production credentials.
Keep Telegram, AI, signing and encryption secrets in the host's secret store.
Set `DB_PATH` to persistent storage outside the source checkout. Production
currently uses `/data/iiko_boss.db`; do not silently switch to a new empty DB.
`ENCRYPTION_KEY` must remain compatible with existing encrypted credentials.
Never print environment values, session links, customer records or database
contents into CI logs or issue descriptions. Use authenticated Git tooling;
never place access tokens in Git remote URLs or command-line arguments.

## Updating or migrating the server

1. Record the running commit and configuration names without copying secrets.
2. Make a consistent SQLite backup using its backup API; check `integrity_check`.
3. Keep an encrypted off-host backup and protect uploaded business files too.
4. Restore and test on a separate server before switching client traffic.
5. Verify owner/manager isolation, existing accounts, uploads and integrations.
6. Keep the previous service available until the migration has been accepted.

A clean Git scan does not revoke previously exposed credentials. Rotate leaked
keys with their providers and update the secret store. Removing a file in a new
commit also does not remove old copies from Git history, forks or cached views.
