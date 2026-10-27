FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=false FTTH_DATA_DIR=/data PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ftth ./ftth
COPY planner ./planner
COPY planner_site ./planner_site
COPY manage.py docker-entrypoint.sh ./
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
 && chmod +x docker-entrypoint.sh \
 && useradd --create-home app && mkdir -p /data && chown app /data
USER app

VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["sh", "-c", "gunicorn planner_site.wsgi --bind 0.0.0.0:${PORT} --workers 3 --timeout 120"]
