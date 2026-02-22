# IDOR Mitigation: Bot conversation ownership

## Summary

Bot conversation endpoints now enforce ownership checks before allowing read/write access to a `conversation_id`.

## Enforcement rules

- If a conversation has `user_id`, requests must match the same authenticated/request user identity.
- If a conversation has `anon_id`, requests must match the bound anonymous session cookie (or explicit anon id on message post).
- On ownership mismatch, endpoints return **403 Forbidden**.

## Covered endpoints

- `POST /api/bot/message`
- `GET /api/bot/messages`
- `GET /api/bot/session/{conversation_id}`
