# IDOR Mitigation: Bot conversation ownership

## Summary

Bot conversation endpoints enforce ownership checks using only server-trusted identity sources. Client-supplied `userId`/`anonId` request fields are never used to establish identity.

## Server-trusted identity sources

- **Authenticated user identity** comes from `request.state.saas_identity.user_id`.
- In tests (`settings.testing == True`), `X-Test-User-Id` can be used to inject identity for test-only coverage.
- **Anonymous identity** comes from bot anon cookies only: `anon_session_id` (canonical) with `anon_id` accepted as legacy fallback.
- `client_session` is not used for bot conversation authorization.

## Enforcement rules

- If a conversation has `user_id`, the current server-authenticated user must match exactly.
- If a conversation has `anon_id`, the current anon cookie value must match exactly.
- If a conversation has neither `user_id` nor `anon_id`, access is denied by default.
- Ownership mismatch returns **403 Forbidden**.
- Request body IDs (`userId`, `anonId`) are optional hints only; if provided and they conflict with server identity, requests are rejected.

## Session creation hardening

- `POST /api/bot/session` binds new conversations from server identity only.
- Authenticated requests always bind `user_id` from server auth and ignore body `userId`.
- Anonymous requests bind `anon_id` from anon cookie; if absent, a new `anon_session_id` is generated and set as an HttpOnly cookie.

## Covered endpoints

- `POST /api/bot/message`
- `GET /api/bot/messages`
- `GET /api/bot/session/{conversation_id}`
