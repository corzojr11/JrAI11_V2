# Deployment Checklist

## Backend env

- `APP_ENV=development|production`
- `BOOTSTRAP_TOKEN=<secure random string>`
- `JWT_SECRET_KEY=<long random secret>`
- `ODDS_API_KEY=<optional if product tolerates degraded odds>`
- `API_FOOTBALL_KEY=<required for live football data>`
- `TELEGRAM_BOT_TOKEN=<optional if publication uses Telegram>`
- `TELEGRAM_CHAT_ID=<optional if publication uses Telegram>`
- `ADMIN_PASSWORD=<optional bootstrap fallback>`
- `FRONTEND_ORIGINS=http://localhost:3000,https://your-frontend-domain`
- `COOKIE_SAMESITE=lax` or `none` only if you need cross-site cookies over HTTPS

## Frontend env

- `NEXT_PUBLIC_API_URL=https://your-backend-domain`

## Runtime rules

- In production, `APP_ENV` must be `production`.
- In production, `JWT_SECRET_KEY` must exist and be at least 32 characters.
- In production, `NEXT_PUBLIC_API_URL` must be present for the frontend build/runtime.
- In production, `COOKIE_SECURE` must be `true` via `APP_ENV=production`.
- `FRONTEND_ORIGINS` must include the deployed frontend origin exactly.

## Route protection

- Public auth routes: `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`
- Authenticated routes: `GET /picks`, `GET /metrics`, `GET /api/picks`, `GET /api/metrics`
- Admin-only routes: `/api/preparation/*`, `/api/publication/export/*`, `/api/publication/telegram/*`, `/api/lab`, `/api/analysis/segments`, `/api/backtest`
- Member/public feed: `/api/publication/overview`

## Preflight steps

1. Verify all env vars above are present in the target environment.
2. Run backend tests.
3. Run frontend lint and production build.
4. Confirm login works and `GET /auth/me` returns the expected role.
5. Confirm `401` triggers refresh once, then logout/redirect if refresh fails.
6. Confirm browser cookies are `HttpOnly`, `Secure` in production, and `SameSite` matches the deployment topology.
7. Confirm CORS only lists the deployed frontend origin(s).
8. Confirm admin-only routes return `403` for non-admin users.
9. Confirm lab routes are accessible only to admin.
10. Confirm publication routes allow member read access but only admin publish/export actions.

## Go/No-Go

- Go only if tests, lint, and build are green.
- No deploy if any production env var is missing.
- No deploy if auth cookies are not secure in production.
- No deploy if CORS allows wildcard origins.
