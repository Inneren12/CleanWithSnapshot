# Feature Modules & Visibility

This project supports organization-level module toggles and user-level UI visibility preferences. These controls are **additive**: when unset they default to enabled, preserving existing behavior.

## Key naming convention

- **Modules** use the `module.<name>` namespace:
  - `module.dashboard`
  - `module.schedule`
  - `module.invoices`
  - `module.quality`
  - `module.teams`
  - `module.analytics`
  - `module.finance`
  - `module.marketing`
  - `module.leads`
  - `module.inventory`
  - `module.training`
  - `module.notifications_center`
  - `module.api`
- **Sub-features** use the base module name as a prefix:
  - `dashboard.weather`
  - `schedule.optimization_ai`
  - `finance.reports`
  - `finance.cash_flow`
  - `api.settings`

## Precedence rules

Visibility is computed with the following precedence:

1. **Organization feature flag**: if an org disables a module key (e.g. `module.schedule = false`), all sub-keys under that module are disabled.
2. **Role permissions**: roles must include the required permission for a module (e.g. finance-only sections require `finance`).
3. **User UI preferences**: users can hide modules/sub-keys for themselves without disabling functionality for others.

In short:

```
visible = org_feature_enabled(key) AND role_allows(key) AND NOT user_hidden(key)
```

## Examples

- Disable scheduling for the org:
  - `module.schedule = false`
- Hide the dispatcher AI suggestions just for a single user:
  - user hidden keys: `schedule.optimization_ai`
- Hide financial reporting widgets for a single user:
  - user hidden keys: `finance.reports`
