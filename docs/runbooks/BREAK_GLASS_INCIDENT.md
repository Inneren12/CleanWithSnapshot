# Break-glass incident response

## During the incident

1. **Confirm incident tracking**
   * Ensure the incident or ticket reference is active (e.g., `INC-12345`).
2. **Request break-glass**
   * Use `POST /v1/admin/break-glass/start` with a clear reason, scope, and TTL.
   * Verify MFA is enabled and verified for the operator.
3. **Use the break-glass token**
   * Include `X-Break-Glass-Token` on all elevated admin requests.
   * Keep the session scoped and time-bound; do not extend TTL beyond policy limits.
4. **Monitor alerts**
   * `BreakGlassActivated` should fire immediately.
   * If `BreakGlassStillActiveTooLong` fires, revoke immediately.

## After the incident

1. **Revoke the session**
   * `POST /v1/admin/break-glass/{session_id}/revoke`
2. **Review & close**
   * `POST /v1/admin/break-glass/{session_id}/review` with outcome notes.
3. **Confirm audit trail**
   * Validate audit entries for:
     * `break_glass_grant_created`
     * `break_glass_use`
     * `break_glass_revoked` or `break_glass_expired`
     * `break_glass_reviewed`
4. **Quarterly access review**
   * Ensure the break-glass session appears in the quarterly access review evidence bundle.

## Troubleshooting

* **403 Break-glass not permitted**
  * Confirm the actor is owner or security role.
* **403 MFA required**
  * Verify MFA is enabled and the session is MFA-verified.
* **Break-glass token invalid/expired**
  * Request a new break-glass grant with valid TTL and incident reference.
