FROM python:3.11.14-slim

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip setuptools==78.1.1 wheel==0.46.2 jaraco.context==6.1.0 \
    && pip install --no-cache-dir -r requirements.txt \
    && python - <<'PY'\nimport importlib.metadata as m\nprint('wheel', m.version('wheel'))\nprint('jaraco.context', m.version('jaraco.context'))\nPY

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
