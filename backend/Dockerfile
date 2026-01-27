FROM python:3.11.14-slim

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade \
        pip \
        setuptools==78.1.1 \
        wheel==0.46.2 \
        jaraco.context==6.1.0 \
    && python -m pip install --no-cache-dir --upgrade -r requirements.txt \
    && set -e; \
        echo "Cleaning stale dist-info..."; \
        find /usr /usr/local -type d -name 'wheel-*.dist-info' 2>/dev/null | grep -v 'wheel-0.46.2.dist-info' | xargs -r rm -rf; \
        find /usr /usr/local -type d -name 'jaraco.context-*.dist-info' 2>/dev/null | grep -v 'jaraco.context-6.1.0.dist-info' | xargs -r rm -rf; \
        echo "Verifying stale dist-info removed..."; \
        test -z "$(find /usr /usr/local -type d -name 'wheel-0.45.1.dist-info' 2>/dev/null)"; \
        test -z "$(find /usr /usr/local -type d -name 'jaraco.context-5.3.0.dist-info' 2>/dev/null)"

RUN groupadd -r app \
    && useradd -r -g app -d /app -s /usr/sbin/nologin app \
    && chown -R app:app /app

COPY --chown=app:app . .

EXPOSE 8000

USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
