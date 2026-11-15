FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIST=/app/frontend/dist PORT=10000
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --disable-pip-version-check -r requirements.txt \
    && useradd --create-home --uid 10001 tripweave \
    && mkdir -p /app/backend/.cache \
    && chown -R tripweave:tripweave /app
COPY --chown=tripweave:tripweave backend/app/ ./app/
COPY --from=frontend --chown=tripweave:tripweave /build/frontend/dist/ /app/frontend/dist/
USER tripweave
EXPOSE 10000
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers"]
