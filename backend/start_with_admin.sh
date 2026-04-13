export APP_ENV=test
export DATABASE_URL=sqlite+aiosqlite:////tmp/e2e.db
export AUTH_SECRET_KEY=e2e-test-secret
export CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
export ADMIN_BASIC_USERNAME=admin
export ADMIN_BASIC_PASSWORD=admin123
export ADMIN_PROXY_AUTH_ENABLED=false
python -m uvicorn app.main:app --port 8000
