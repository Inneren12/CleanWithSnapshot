# Incident Post-Mortem Process (Blameless)

> **Blameless principle:** Post-mortems focus on learning and systemic improvement, not blame.

## Purpose

Provide a lightweight, consistent post-mortem workflow for **P0–P2 incidents** that can be completed in **30 minutes** for a simple incident.

## When a Post-Mortem Is Required

- **P0:** Always required.
- **P1:** Required when customer impact is non-trivial or lasts > 15 minutes.
- **P2:** Required when it reveals a systemic gap, security concern, or repeatable failure.

## Ownership

- **Incident owner (PM):** Drives the post-mortem, ensures data is captured, and schedules review.
- **Primary responder:** Provides timeline, technical details, and corrective actions.
- **Contributors:** SMEs who add facts or follow-ups.

## Time Expectations

- **Draft within 24–48 hours** of incident resolution.
- **Review within 5 business days** with relevant stakeholders.
- **Actions created immediately** after review (or earlier if urgent).

## Workflow (30-minute ready)

1. **Create a new post-mortem** using the template:
   - `docs/postmortems/INCIDENT_POSTMORTEM_TEMPLATE.md`
2. **Fill in the metadata and timeline** (aim for 10–15 minutes).
3. **Summarize impact and root cause** in clear, factual language.
4. **List corrective actions** with **owner** and **due date**:
   - Distinguish **short-term** vs **long-term** actions.
5. **Review** with responders and stakeholders, then mark **Status: Reviewed**.
6. **Track actions** until completion, then mark **Status: Closed**.

## Follow-Up Tracking Expectations

- Every action item must have:
  - **Owner** (accountable person or team)
  - **Due date**
  - **Tracking link** (ticket, issue, or task ID)
- The post-mortem is **not complete** until actions are tracked.
- Escalate overdue action items in the next ops review.

## Severity Definitions (P0–P2)

- **P0:** Customer-impacting outage, security incident, or data loss risk.
- **P1:** Degraded service with customer impact but not a full outage.
- **P2:** Internal-only or limited-impact incident with minimal customer impact.

## References

- Incident response runbooks: `docs/runbooks/README.md`
- Operations guide: `OPERATIONS.md`
- Security policy: `docs/SECURITY_VULN_POLICY.md`
