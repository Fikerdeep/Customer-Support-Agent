# Deploying Loopp for free — Vercel (frontend) + Render (backend)

**Architecture:** the browser only talks to the Vercel domain; Next.js rewrites `/api/*` to the Render
backend server-side, so **no CORS configuration is needed**. The backend is a free Render Docker web
service; the frontend is a free Vercel project.

```
browser ──▶ Vercel (Next.js)  ──/api/* rewrite──▶  Render (FastAPI)  ──▶ OpenAI + LangSmith
```

> Hosting is free, but **OpenAI tokens are billed to your key** and **LangSmith** has a free monthly
> trace quota. Free tiers change — verify current limits.

---

## 0. Push the repo to GitHub

Both platforms deploy from Git.

```bash
git add -A && git commit -m "Loopp refund agent"
gh repo create loopp-refund-agent --private --source=. --push   # or create on github.com and `git push`
```

---

## 1. Backend on Render (Docker, free)

**Option A — Blueprint (uses [`render.yaml`](render.yaml)):**
1. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint** → connect this repo.
2. Render reads `render.yaml` and creates the `loopp-backend` service. When prompted, paste the secret
   env vars: **`OPENAI_API_KEY`** and **`LANGSMITH_API_KEY`**.
3. Click **Apply** and wait for the service to go **Live**.

**Option B — manual:** New → **Web Service** → connect repo → **Root Directory** `backend`,
**Runtime** `Docker`, **Health Check Path** `/api/health`, add the env vars
(`OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=loopp-refund-agent`).

**Verify:** open `https://<your-backend>.onrender.com/api/health` →
`{"provider":"openai","model":"gpt-4o","api_key_configured":true,"langsmith_tracing":true,...}`.
Copy that base URL — you need it for Vercel. (First load is slow: free services cold-start.)

---

## 2. Frontend on Vercel (Next.js, free)

1. [vercel.com/new](https://vercel.com/new) → import the same repo.
2. **Root Directory** → `frontend` (Framework auto-detects as Next.js).
3. **Environment Variables** → add `BACKEND_URL` = your Render URL
   (e.g. `https://loopp-backend.onrender.com`). Apply to **Production** and **Preview**.
4. **Deploy**. You get `https://<project>.vercel.app`.

The `/api/*` rewrite in [`frontend/next.config.mjs`](frontend/next.config.mjs) reads `BACKEND_URL` at
build time, so the proxy points at Render automatically.

---

## 3. Verify the live app

1. **Warm the backend first** — open `https://<backend>.onrender.com/api/health` so it's awake (free
   services sleep after ~15 min idle and take ~30–60s to wake; the first chat would otherwise time out).
2. Open the Vercel URL → run a refund in the chat → check `/admin` for the trace.
3. Confirm traces appear in LangSmith project **`loopp-refund-agent`**.

---

## Notes & gotchas

- **Cold starts (free tier):** warm the Render URL right before any demo/Loom recording.
- **SQLite is ephemeral:** the DB resets on redeploy/restart and auto-seeds on boot — fine for a demo.
  For persistence, provision a free Postgres (Neon/Supabase/Render) and point SQLAlchemy at it
  (`app/db/database.py`); the ORM models don't change.
- **Direct (non-proxy) calls:** if you ever bypass the Next rewrite and call the backend from the
  browser, add your Vercel domain to CORS in `app/main.py` — not needed with the proxy.
- **Redeploys:** both platforms auto-deploy on push to the default branch.
