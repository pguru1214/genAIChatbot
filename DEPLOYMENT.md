# Free personal-demo deployment

The root Dockerfile builds React with Node 22 and serves the compiled frontend
and FastAPI API together with Python 3.13. It uses a single worker and binds to
`0.0.0.0:$PORT`. No separate frontend hosting, paid database, disk, cron or worker
is provisioned. Deploy the GitHub branch `deploy/free-render` to a Render web
service with runtime **Docker**, compute plan **Free**, region **Singapore**.

Set these runtime variables in the hosting provider's secret settings:

- `APP_MODE=live`
- `PUBLIC_DEPLOYMENT=true`
- `DEPLOYMENT_ACCESS_PASSWORD`: a unique random password, at least 20 characters.
- `SESSION_SIGNING_KEY`: a separate random secret, at least 32 characters.
- `GEMINI_API_KEY`, `GEMINI_MODEL`, optional `GEMINI_FALLBACK_API_KEY` and
  `GEMINI_FALLBACK_MODEL`: existing free-tier account credentials/model.
- `GEOAPIFY_API_KEY`: existing Free-plan key.
- `GEOAPIFY_DAILY_CREDIT_LIMIT=2400`
- `DATABASE_URL=sqlite:///./tripweave.db`
- `CORS_ORIGINS=[]` (the UI and API use the same origin).

`FRONTEND_DIST` and `PORT` have container defaults. Never commit `.env`, API keys,
the access password, or the signing key. Docker copies only application source,
locked dependencies and the compiled frontend, not local databases or credentials.

## Access and verification

The public URL shows a password screen. API routes, documentation and frontend
assets require a signed, Secure, HttpOnly access cookie. `/api/health` stays
public for readiness checks. The cookie expires after 12 hours. Login attempts
are bounded per client. This is private-demo access, not individual user accounts:
people who share the access password also share access to backend trip records.

After deployment, verify `/api/health`, unauthenticated API rejection, access
login, compiled frontend assets, a local greeting and an actual live travel turn.
Do not report the deployment successful until Render reports **live** and these
checks pass. Environment changes require a fresh deploy to take effect.

## Zero-cost limits

- Keep the service on **Free** and the workspace without a payment method.
  Render documents that otherwise bandwidth/build overages can be billed even
  for Free services. No paid fallback or automatic upgrade is configured here.
- Free web services sleep after 15 idle minutes; waking may take about a minute.
  Workspace free instance hours are shared with existing services.
- SQLite records, checkpoints and local quota ledgers are temporary: Render
  discards filesystem changes on idle shutdown, restart or redeploy. The browser
  shows only current-page chat history, as requested. Do not rely on this demo
  as permanent storage. Provider-side quotas still apply after an app restart.
- No Render free PostgreSQL database is created: it expires after 30 days.
- Gemini and Geoapify must remain on eligible free tiers. Quota or provider
  failures are reported rather than triggering paid services.
- Gmail/Calendar execution and reminders remain the application's existing
  preview-only capabilities; hosting does not enable those integrations.

Official reference: https://render.com/docs/free
