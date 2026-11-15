# Free personal-demo deployment

## Live deployment — verified 15 November 2026

- URL: https://tripweave-guru-demo.onrender.com
- Dashboard: https://dashboard.render.com/web/srv-dbsqm1bl550s7397cmgg
- Workspace: guru's workspace; Singapore region; **Free** compute plan.
- Source: https://github.com/pguru1214/genAIChatbot/tree/deploy/free-render
- Deployed commit: `82f657b4e54de4df425f95c34601fcc2bcb26e0f`.
- Automatic deploys: **off**, to avoid unintended rebuilds. Update the deployment
  branch and manually deploy when changes are ready.
- Access password: stored in the ignored local `backend/.env` under
  `DEPLOYMENT_ACCESS_PASSWORD`, and in Render's environment-variable settings.
  Do not commit or paste it into public repository files.
- Verified: live health endpoint, unauthorized API rejection, browser-Origin
  access login, compiled frontend assets without embedded credentials, local
  greeting/non-travel guardrails, and a real Gemini itinerary with three meal
  windows, nine restaurant references and three destination stay references.
  The disposable verification itinerary was deleted after the test.
- Validation before release: 167 backend tests and the frontend production build
  passed. Docker build/startup were verified by the successful Render deployment.

The root Dockerfile builds React with Node 22 and serves the compiled frontend
and FastAPI API together with Python 3.13. It uses a single worker and binds to
`0.0.0.0:$PORT`. No separate frontend hosting, paid database, disk, cron or worker
is provisioned. Deploy the GitHub branch `deploy/free-render` to a Render web
service with runtime **Docker**, compute plan **Free**, region **Singapore**.

Set these runtime variables in the hosting provider's secret settings:

- `APP_MODE=live`
- `PUBLIC_DEPLOYMENT=true`
- `DEPLOYMENT_ACCESS_PASSWORD`: access password, at least 8 characters.
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
