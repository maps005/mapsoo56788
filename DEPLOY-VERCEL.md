# Deploying ArchPlanner on Vercel

Vercel runs the app as a serverless Python function and serves the static files from its CDN. It is a quick way to
put a demo or a small team online. For full production use (survey photos, company logos, long auto-designs on large
areas) the Docker deployment in `DEPLOY.md` is still the better fit - see **Limits** below.

## Files

| File | What it does |
|---|---|
| `vercel.json` | Build command, static output folder, function settings (60 s, 1 GB) and the rewrite that sends every page to Django |
| `api/index.py` | The function: Django's WSGI application |
| `vercel_build.sh` | Installs the requirements, collects static files into `public/static`, migrates the database and creates the first administrator |
| `.vercelignore` | Keeps local data, secrets, client files and the virtual environment out of the upload |

## 1. Create a PostgreSQL database

A serverless function cannot keep a SQLite file, so the app needs an external database. Any PostgreSQL works:
**Vercel Storage → Postgres (Neon)**, Neon, Supabase or your own server. Copy its connection string
(`postgres://user:password@host/dbname?sslmode=require`).

## 2. Import the project

1. In Vercel: **Add New → Project**, import `maps005/mapsoo56788` from GitHub.
2. Framework preset: **Other**. Leave the build and output settings empty - `vercel.json` sets them.

## 3. Environment variables (Project → Settings → Environment Variables)

| Variable | Value |
|---|---|
| `DATABASE_URL` | the PostgreSQL connection string from step 1 (required) |
| `DJANGO_SECRET_KEY` | a long random string (required) |
| `DJANGO_SUPERUSER_USERNAME` | first administrator's username (first deploy) |
| `DJANGO_SUPERUSER_PASSWORD` | their password - remove it after the first deploy |
| `DJANGO_SUPERUSER_EMAIL` | their email (optional) |
| `DJANGO_ALLOWED_HOSTS` | your custom domain, e.g. `planner.example.com` (the `*.vercel.app` addresses are allowed already) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | the same domain with https, e.g. `https://planner.example.com` |
| `AI_CHAT_KEY`, `AI_CHAT_MODEL` | Groq key and model for the AI assistant (optional) |
| `PHOTO_AI_PROVIDER`, `PHOTO_AI_KEY`, `PHOTO_AI_MODEL`, `PHOTO_AI_URL` | Photo AI (optional, see `.env.example`) |

`DJANGO_DEBUG` is off on Vercel unless you set it. Never put the keys in the repository.

## 4. Deploy

Press **Deploy**. The build migrates the database and creates the administrator; open the `*.vercel.app` address and
sign in. Every push to `main` deploys again (migrations run on each build).

## Limits on Vercel

- **Uploaded files are temporary.** Survey photos, company logos and imported photo files are written to `/tmp`,
  which is cleared whenever Vercel starts a new instance. Designs, companies, users and comments are safe in
  PostgreSQL. Use the Docker deployment if you need photos and logos kept.
- **Request size: 4.5 MB.** Larger KMZ / Excel imports and photos are refused by Vercel before they reach the app.
- **60 seconds per request.** Auto-design and full package exports of very large areas can take longer.
- **Sign-in throttling and the AI rate limit** are counted per instance, so they are looser than on a single server.
