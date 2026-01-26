# Twilio Vendor Status — NOT IN USE

**Status:** NOT IN USE (Twilio is not integrated, not active, and does not process data).

## Scope and environments checked
The following environments have been reviewed for Twilio usage and configuration:

- **dev**
- **e2e**
- **staging**
- **prod**

## Current declaration (audit-ready)
Twilio is **NOT used in production or staging**, and is also **not used in dev or e2e**.

**Confirmations:**
- **No API keys configured:** There are no Twilio credentials configured in environment files or runtime settings.
- **No Twilio client libraries imported:** The Twilio vendor SDK is not installed or imported by the application.
- **No data sent to Twilio:** Because Twilio is not configured or enabled, no SMS/call data is transmitted to Twilio.

**Owner (vendor accountability):**
- **Service owner:** Security & Compliance Lead
- **Operational owner:** Platform Engineering Lead

## Controls that prevent accidental use
1. **Configuration defaults to off:** SMS and call modes default to `off`.
2. **No Twilio env vars allowed:** Twilio-specific environment variables are not permitted in dev, e2e, staging, or production.
3. **Code review requirement:** Any change introducing Twilio configuration, credentials, or activation requires security and compliance review.
4. **Optional CI guardrail (future):** Add a CI check to reject `TWILIO_*` variables or Twilio enablement in configuration files.

## Risk statement
**Risks:**
- **Accidental enablement:** Future changes could set SMS/call modes to Twilio without formal approval.
- **Credential leakage:** Twilio credentials could be added to configuration or logs inadvertently.

**Mitigations:**
- **No env vars allowed:** Block Twilio variables in configuration and deployment manifests.
- **Code review requirement:** Security/compliance approval required for any Twilio-related change.
- **Optional CI check:** Automated detection of `TWILIO_*` entries and `sms_mode=twilio` / `call_mode=twilio` in configuration.

## If Twilio is enabled in the future
**Activation is forbidden without completing every item in this checklist.**

1. **Data Processing Agreement (DPA):** Execute and archive a signed DPA with Twilio.
2. **Data map:** Update data flow diagrams to include Twilio, including data categories, purposes, and recipients.
3. **Retention settings:** Define and document retention, deletion, and log redaction policies for Twilio data.
4. **Abuse controls:** Implement rate limits, fraud/abuse monitoring, and opt-out handling.
5. **Incident runbook:** Create a vendor incident response runbook and include Twilio contacts and escalation steps.
