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
    && rm -rf \
        /usr/local/lib/python*/site-packages/wheel-*.dist-info \
        /usr/local/lib/python*/site-packages/wheel \
        /usr/local/lib/python*/site-packages/jaraco.context-*.dist-info \
        /usr/local/lib/python*/site-packages/jaraco/context* \
        /usr/lib/python*/dist-packages/wheel-*.dist-info \
        /usr/lib/python*/dist-packages/wheel \
        /usr/lib/python*/dist-packages/jaraco.context-*.dist-info \
        /usr/lib/python*/dist-packages/jaraco/context* \
        || true \
    && python -m pip install --no-cache-dir --upgrade --force-reinstall --no-deps \
        wheel==0.46.2 \
        jaraco.context==6.1.0 \
    && python -m pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
