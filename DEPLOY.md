# Deploying the ArchPlanner to your own server

The production stack runs in Docker:

- **web**: the Django app, served by gunicorn.
- **db**: PostgreSQL 16.
- **caddy**: obtains and renews a free HTTPS certificate automatically.

All data lives in Docker volumes on the server.

## What you need

- A Linux VPS (Ubuntu 22.04/24.04 or Debian 12) with at least 1 GB RAM (2 GB recommended), and SSH access with sudo.
- A domain or sub-domain, for example `planner.yourcompany.co.ke`, with an **A record pointing to the server's IP address**.
- Ports **80 and 443** open to the internet. If something else already uses them, such as nginx for another site, see "Server already runs nginx" below.

## 1. Install Docker on the server

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # then log out and back in
docker compose version          # should print v2.x
```

## 2. Copy the app to the server

On your Windows PC, inside the `faibaplaning` folder:

```bash
.venv\Scripts\python deploy\make_bundle.py
scp out\faibaplaning-deploy.tar.gz youruser@your-server:/tmp/
```

On the server:

```bash
sudo mkdir -p /opt && cd /opt
sudo tar xzf /tmp/faibaplaning-deploy.tar.gz
sudo chown -R $USER:$USER /opt/faibaplaning
cd /opt/faibaplaning
```

## 3. Configure

```bash
./deploy/make-env.sh
```

The script asks for the domain and admin username. It writes `.env` with random secrets and prints the first admin password, so **note it down**.

## 4. Start

```bash
docker compose up -d --build
docker compose logs -f web      # wait for "Listening at: http://0.0.0.0:8000", then Ctrl+C
```

Open `https://your-domain`. The certificate is issued within about a minute of the first visit. Sign in with the admin account, then:

1. Change the admin password: **Admin**, then **Change password**. Then delete the `DJANGO_SUPERUSER_PASSWORD` line from `.env`.
2. Create user accounts: **Admin**, then **Users**, then **Add**.
3. Give approvers the permission **"planner | project | Can approve an FTTH design for issue"**. Creating an "Approvers" group with that permission is easiest.

## 5. Daily backups

```bash
crontab -e
# add this line:
30 2 * * * cd /opt/faibaplaning && ./deploy/backup.sh >> backups/backup.log 2>&1
```

Backups go to `/opt/faibaplaning/backups/` (14 days kept). Copy them off the server regularly, for example with `scp` or your VPS provider's snapshot feature.

To restore a database backup:

```bash
gunzip -c backups/db-YYYYMMDD-HHMM.sql.gz | docker compose exec -T db psql -U ftth ftth
```

## Updating to a new version

Build a new bundle on your PC, copy it up, and on the server:

```bash
cd /opt && tar xzf /tmp/faibaplaning-deploy.tar.gz     # .env and data volumes are kept
cd faibaplaning && docker compose up -d --build
```

Migrations run automatically on start.

## Server already runs nginx (other sites)

Do not start Caddy. Run only the app and database:

```bash
docker compose up -d --build web db
```

The app then listens on `127.0.0.1:8000`. Use `deploy/nginx-ftth.conf` as the site config (instructions are inside it), and add HTTPS with `sudo certbot --nginx -d your-domain`.

## Moving existing projects from your PC (new server only)

Project owners are matched by username, so first create the same usernames on the server, for example `admin`.

On your PC:

```bash
.venv\Scripts\python manage.py dumpdata planner --natural-foreign --indent 1 -o projects.json
scp projects.json youruser@your-server:/opt/faibaplaning/
scp -r data\media\photos youruser@your-server:/opt/faibaplaning/photos
```

On the server:

```bash
cd /opt/faibaplaning
docker compose cp projects.json web:/tmp/projects.json
docker compose exec web python manage.py loaddata /tmp/projects.json
docker compose cp photos/. web:/data/media/photos/      # only if you have survey photos
docker compose exec --user root web chown -R app /data/media
```

Do this once, on a server that has no projects yet. Loading the same file again overwrites those projects.

## Troubleshooting

| Symptom | Check |
|---|---|
| Browser shows a certificate error | DNS A record must point to this server, and ports 80/443 must be open (`sudo ufw allow 80,443/tcp`). See `docker compose logs caddy` |
| "Bad Request (400)" | `DJANGO_ALLOWED_HOSTS` in `.env` must equal the domain. Restart with `docker compose up -d` |
| "CSRF verification failed" | `DJANGO_CSRF_TRUSTED_ORIGINS` must be `https://your-domain` |
| App not starting | `docker compose logs web` |
