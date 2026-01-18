"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const RULE_TRIGGERS = [
  "payment_failed",
  "negative_review",
  "low_inventory",
  "worker_no_show",
  "high_value_lead",
] as const;

const CONDITION_FIELDS = ["priority", "team_id", "service_type", "amount_cents", "inventory_status"] as const;
const CONDITION_OPERATORS = ["equals", "not_equals", "contains", "greater_than", "less_than"] as const;
const ACTION_TYPES = ["create_notification_event", "send_email", "send_sms", "create_task"] as const;

type RuleCondition = {
  id: string;
  field: string;
  operator: string;
  value: string;
};

type RuleAction = {
  id: string;
  type: string;
  target: string;
  message: string;
};

type RuleDefinition = {
  id: string;
  name: string;
  description: string;
  trigger: string;
  status: "active" | "paused" | "draft";
  updated_at: string;
  dry_run: boolean;
  conditions: RuleCondition[];
  actions: RuleAction[];
};

type RuleRun = {
  id: string;
  rule_id: string;
  rule_name: string;
  status: "success" | "skipped" | "error";
  trigger: string;
  executed_at: string;
  duration_ms: number;
  dry_run: boolean;
  notes: string;
};

const INITIAL_RULES: RuleDefinition[] = [
  {
    id: "rule-ops-001",
    name: "Payment failure escalation",
    description: "Notify finance and create a follow-up task when Stripe retries fail.",
    trigger: "payment_failed",
    status: "active",
    updated_at: "2024-04-12T15:12:00Z",
    dry_run: false,
    conditions: [
      { id: "cond-1", field: "priority", operator: "equals", value: "high" },
      { id: "cond-2", field: "amount_cents", operator: "greater_than", value: "25000" },
    ],
    actions: [
      {
        id: "action-1",
        type: "create_notification_event",
        target: "finance_team",
        message: "High-value payment failed. Escalate to finance lead.",
      },
      {
        id: "action-2",
        type: "create_task",
        target: "collections_queue",
        message: "Create follow-up task for failed payment.",
      },
    ],
  },
  {
    id: "rule-ops-002",
    name: "Low inventory pulse",
    description: "Alert operations when inventory status flips to low.",
    trigger: "low_inventory",
    status: "paused",
    updated_at: "2024-04-09T09:42:00Z",
    dry_run: true,
    conditions: [{ id: "cond-3", field: "inventory_status", operator: "equals", value: "low" }],
    actions: [
      {
        id: "action-3",
        type: "send_email",
        target: "ops-managers@cleanwithsnapshot.com",
        message: "Inventory is low. Reorder recommended items.",
      },
    ],
  },
];

const INITIAL_RUNS: RuleRun[] = [
  {
    id: "run-1001",
    rule_id: "rule-ops-001",
    rule_name: "Payment failure escalation",
    status: "success",
    trigger: "payment_failed",
    executed_at: "2024-04-12T16:02:11Z",
    duration_ms: 182,
    dry_run: false,
    notes: "Notification created, task queued.",
  },
  {
    id: "run-1002",
    rule_id: "rule-ops-002",
    rule_name: "Low inventory pulse",
    status: "skipped",
    trigger: "low_inventory",
    executed_at: "2024-04-12T12:40:28Z",
    duration_ms: 96,
    dry_run: true,
    notes: "Dry-run: would send 1 email.",
  },
  {
    id: "run-1003",
    rule_id: "rule-ops-001",
    rule_name: "Payment failure escalation",
    status: "error",
    trigger: "payment_failed",
    executed_at: "2024-04-10T09:01:43Z",
    duration_ms: 210,
    dry_run: false,
    notes: "Email delivery adapter unavailable.",
  },
];

function generateLocalId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function createEmptyRule(): RuleDefinition {
  return {
    id: generateLocalId("rule"),
    name: "",
    description: "",
    trigger: "",
    status: "draft",
    updated_at: new Date().toISOString(),
    dry_run: true,
    conditions: [{ id: generateLocalId("cond"), field: "", operator: "", value: "" }],
    actions: [{ id: generateLocalId("action"), type: "", target: "", message: "" }],
  };
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function statusPill(status: RuleDefinition["status"]) {
  const className = status === "active" ? "pill pill-success" : status === "paused" ? "pill pill-warning" : "pill";
  return <span className={className}>{status}</span>;
}

function runStatusPill(status: RuleRun["status"]) {
  const className = status === "success" ? "pill pill-success" : status === "error" ? "pill pill-warning" : "pill";
  return <span className={className}>{status}</span>;
}

function validateRuleDraft(draft: RuleDefinition) {
  const errors: string[] = [];
  if (!draft.name.trim()) errors.push("Rule name is required.");
  if (!draft.trigger.trim()) errors.push("Trigger is required.");
  if (!draft.conditions.length) errors.push("Add at least one condition.");
  if (!draft.actions.length) errors.push("Add at least one action.");
  if (draft.conditions.some((condition) => !condition.field || !condition.operator || !condition.value)) {
    errors.push("All conditions must include field, operator, and value.");
  }
  if (draft.actions.some((action) => !action.type || !action.target || !action.message)) {
    errors.push("All actions must include type, target, and message.");
  }
  return errors;
}

export default function RulesBuilderPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [rules, setRules] = useState<RuleDefinition[]>(() => INITIAL_RULES);
  const [activeRuleId, setActiveRuleId] = useState<string | null>(() => INITIAL_RULES[0]?.id ?? null);
  const [draft, setDraft] = useState<RuleDefinition>(() => INITIAL_RULES[0] ?? createEmptyRule());
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [testEventJson, setTestEventJson] = useState("{\n  \"priority\": \"high\",\n  \"amount_cents\": 32000\n}");
  const [testDryRun, setTestDryRun] = useState(true);
  const [testResponse, setTestResponse] = useState<string | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [runs, setRuns] = useState<RuleRun[]>(() => INITIAL_RUNS);
  const [runsStatus, setRunsStatus] = useState<string | null>(null);
  const [runFilter, setRunFilter] = useState("all");
  const [runRuleFilter, setRunRuleFilter] = useState("all");

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY) || "";
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY) || "";
    setUsername(storedUsername);
    setPassword(storedPassword);
  }, []);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("notifications_center.rules_builder", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      {
        key: "notifications-rules",
        label: "Rules Builder",
        href: "/admin/notifications/rules",
        featureKey: "notifications_center.rules_builder",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      { key: "quality", label: "Quality", href: "/admin/quality", featureKey: "module.quality" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
      {
        key: "roles",
        label: "Roles & Permissions",
        href: "/admin/iam/roles",
        featureKey: "module.teams",
        requiresPermission: "users.manage",
      },
    ];
    return candidates
      .filter((entry) => !entry.requiresPermission || permissionKeys.includes(entry.requiresPermission))
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, requiresPermission, ...link }) => link);
  }, [featureOverrides, hiddenKeys, permissionKeys, profile, visibilityReady]);

  const loadProfile = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/profile`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as AdminProfile;
      setProfile(data);
    } else {
      setProfile(null);
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    loadFeatureConfig();
  }, [loadFeatureConfig]);

  useEffect(() => {
    loadUiPrefs();
  }, [loadUiPrefs]);

  useEffect(() => {
    if (!activeRuleId) return;
    const match = rules.find((rule) => rule.id === activeRuleId);
    if (match) {
      setDraft({ ...match });
      setValidationErrors([]);
    }
  }, [activeRuleId, rules]);

  const handleSaveCredentials = () => {
    localStorage.setItem(STORAGE_USERNAME_KEY, username);
    localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved admin credentials.");
  };

  const handleClearCredentials = () => {
    localStorage.removeItem(STORAGE_USERNAME_KEY);
    localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setStatusMessage("Cleared credentials.");
  };

  const startNewRule = () => {
    setDraft(createEmptyRule());
    setActiveRuleId(null);
    setValidationErrors([]);
    setStatusMessage(null);
  };

  const saveRule = () => {
    const errors = validateRuleDraft(draft);
    setValidationErrors(errors);
    if (errors.length) {
      setStatusMessage("Fix validation errors before saving.");
      return;
    }
    const updatedRule: RuleDefinition = {
      ...draft,
      updated_at: new Date().toISOString(),
    };
    setRules((current) => {
      const exists = current.some((rule) => rule.id === updatedRule.id);
      if (exists) {
        return current.map((rule) => (rule.id === updatedRule.id ? updatedRule : rule));
      }
      return [updatedRule, ...current];
    });
    setActiveRuleId(updatedRule.id);
    setStatusMessage("Rule saved locally. Wire up /v1/admin/rules to persist.");
  };

  const updateCondition = (id: string, updates: Partial<RuleCondition>) => {
    setDraft((current) => ({
      ...current,
      conditions: current.conditions.map((condition) =>
        condition.id === id ? { ...condition, ...updates } : condition
      ),
    }));
  };

  const updateAction = (id: string, updates: Partial<RuleAction>) => {
    setDraft((current) => ({
      ...current,
      actions: current.actions.map((action) => (action.id === id ? { ...action, ...updates } : action)),
    }));
  };

  const addCondition = () => {
    setDraft((current) => ({
      ...current,
      conditions: [
        ...current.conditions,
        { id: generateLocalId("cond"), field: "", operator: "", value: "" },
      ],
    }));
  };

  const removeCondition = (id: string) => {
    setDraft((current) => ({
      ...current,
      conditions: current.conditions.filter((condition) => condition.id !== id),
    }));
  };

  const addAction = () => {
    setDraft((current) => ({
      ...current,
      actions: [...current.actions, { id: generateLocalId("action"), type: "", target: "", message: "" }],
    }));
  };

  const removeAction = (id: string) => {
    setDraft((current) => ({
      ...current,
      actions: current.actions.filter((action) => action.id !== id),
    }));
  };

  const rulePayload = useMemo(() => {
    return {
      id: draft.id,
      name: draft.name,
      description: draft.description,
      trigger: draft.trigger,
      status: draft.status,
      dry_run: draft.dry_run,
      conditions: draft.conditions.map(({ field, operator, value }) => ({ field, operator, value })),
      actions: draft.actions.map(({ type, target, message }) => ({ type, target, message })),
    };
  }, [draft]);

  const runTest = async () => {
    const errors = validateRuleDraft(draft);
    setValidationErrors(errors);
    if (errors.length) {
      setStatusMessage("Fix validation errors before testing.");
      return;
    }
    let eventPayload: Record<string, unknown> = {};
    try {
      eventPayload = testEventJson ? (JSON.parse(testEventJson) as Record<string, unknown>) : {};
    } catch (error) {
      setStatusMessage("Test event JSON is invalid.");
      setTestResponse(null);
      return;
    }

    setTestLoading(true);
    setStatusMessage(null);
    setTestResponse(null);

    try {
      const response = await fetch(`${API_BASE}/rules/test`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ rule: rulePayload, event: eventPayload, dry_run: testDryRun }),
      });
      if (response.ok) {
        const data = await response.json();
        setTestResponse(JSON.stringify(data, null, 2));
        setStatusMessage("Test completed. Review response below.");
      } else {
        setTestResponse(await response.text());
        setStatusMessage("Test failed. Check API response.");
      }
    } catch (error) {
      setStatusMessage("Unable to reach /rules/test.");
    } finally {
      setTestLoading(false);
    }
  };

  const refreshRuns = async () => {
    setRunsStatus("Loading runs...");
    try {
      const response = await fetch(`${API_BASE}/v1/admin/rules/runs`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as RuleRun[];
        setRuns(data);
        setRunsStatus("Runs updated.");
      } else {
        setRunsStatus("Unable to load runs from API.");
      }
    } catch (error) {
      setRunsStatus("Unable to reach runs API. Showing local samples.");
    }
  };

  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      if (runFilter !== "all" && run.status !== runFilter) return false;
      if (runRuleFilter !== "all" && run.rule_id !== runRuleFilter) return false;
      return true;
    });
  }, [runFilter, runRuleFilter, runs]);

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="notifications-rules" />
        <div className="admin-card admin-section">
          <h1>Rules Builder</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="notifications-rules" />
      <div className="admin-section">
        <h1>Rules Builder</h1>
        <p className="muted">
          Draft, validate, and preview automation rules before wiring up the backend engine.
        </p>
      </div>

      {statusMessage ? <p className="alert alert-info">{statusMessage}</p> : null}

      <div className="admin-card admin-section">
        <h2>Credentials</h2>
        <div className="admin-actions">
          <input placeholder="Username" value={username} onChange={(event) => setUsername(event.target.value)} />
          <input
            placeholder="Password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button className="btn btn-primary" type="button" onClick={handleSaveCredentials}>
            Save
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear
          </button>
        </div>
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <div>
            <h2>Rules list</h2>
            <p className="muted">Track active, paused, and draft rules across teams.</p>
          </div>
          <button className="btn btn-primary" type="button" onClick={startNewRule}>
            New rule
          </button>
        </div>
        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Dry run</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id}>
                  <td>
                    <strong>{rule.name}</strong>
                    <div className="muted">{rule.description || "—"}</div>
                  </td>
                  <td>{rule.trigger || "—"}</td>
                  <td>{statusPill(rule.status)}</td>
                  <td>{rule.dry_run ? "Yes" : "No"}</td>
                  <td>{formatTimestamp(rule.updated_at)}</td>
                  <td>
                    <button className="btn btn-ghost" type="button" onClick={() => setActiveRuleId(rule.id)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <div>
            <h2>{activeRuleId ? "Edit rule" : "Create new rule"}</h2>
            <p className="muted">Define triggers, conditions, and actions before deploying.</p>
          </div>
          <div className="pill-row">
            {draft.status ? statusPill(draft.status) : null}
            <span className="pill">Trigger: {draft.trigger || "pending"}</span>
          </div>
        </div>

        {validationErrors.length ? (
          <div className="alert alert-warning">
            <strong>Validation</strong>
            <ul>
              {validationErrors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="form-grid">
          <label>
            <span>Rule name</span>
            <input
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder="Example: Escalate failed payments"
            />
          </label>
          <label>
            <span>Trigger</span>
            <select
              value={draft.trigger}
              onChange={(event) => setDraft((current) => ({ ...current, trigger: event.target.value }))}
            >
              <option value="">Select trigger</option>
              {RULE_TRIGGERS.map((trigger) => (
                <option key={trigger} value={trigger}>
                  {trigger}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Status</span>
            <select
              value={draft.status}
              onChange={(event) =>
                setDraft((current) => ({ ...current, status: event.target.value as RuleDefinition["status"] }))
              }
            >
              <option value="draft">Draft</option>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
            </select>
          </label>
          <label className="full">
            <span>Description</span>
            <textarea
              rows={3}
              value={draft.description}
              onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              placeholder="What should this rule accomplish?"
            />
          </label>
        </div>

        <div className="settings-form" style={{ marginTop: 20 }}>
          <div className="section-heading">
            <h3>Conditions</h3>
            <button className="btn btn-ghost" type="button" onClick={addCondition}>
              Add condition
            </button>
          </div>
          {draft.conditions.map((condition) => (
            <div key={condition.id} className="form-grid" style={{ marginBottom: 12 }}>
              <label>
                <span>Field</span>
                <select value={condition.field} onChange={(event) => updateCondition(condition.id, { field: event.target.value })}>
                  <option value="">Select field</option>
                  {CONDITION_FIELDS.map((field) => (
                    <option key={field} value={field}>
                      {field}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Operator</span>
                <select
                  value={condition.operator}
                  onChange={(event) => updateCondition(condition.id, { operator: event.target.value })}
                >
                  <option value="">Select operator</option>
                  {CONDITION_OPERATORS.map((operator) => (
                    <option key={operator} value={operator}>
                      {operator}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Value</span>
                <input
                  value={condition.value}
                  onChange={(event) => updateCondition(condition.id, { value: event.target.value })}
                  placeholder="Value"
                />
              </label>
              <label>
                <span>Remove</span>
                <button className="btn btn-ghost" type="button" onClick={() => removeCondition(condition.id)}>
                  Delete
                </button>
              </label>
            </div>
          ))}
        </div>

        <div className="settings-form" style={{ marginTop: 20 }}>
          <div className="section-heading">
            <h3>Actions</h3>
            <button className="btn btn-ghost" type="button" onClick={addAction}>
              Add action
            </button>
          </div>
          {draft.actions.map((action) => (
            <div key={action.id} className="form-grid" style={{ marginBottom: 12 }}>
              <label>
                <span>Action type</span>
                <select value={action.type} onChange={(event) => updateAction(action.id, { type: event.target.value })}>
                  <option value="">Select action</option>
                  {ACTION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Target</span>
                <input
                  value={action.target}
                  onChange={(event) => updateAction(action.id, { target: event.target.value })}
                  placeholder="ops-team, email, phone, or queue"
                />
              </label>
              <label className="full">
                <span>Message</span>
                <textarea
                  rows={2}
                  value={action.message}
                  onChange={(event) => updateAction(action.id, { message: event.target.value })}
                  placeholder="Describe what the action should do."
                />
              </label>
              <label>
                <span>Remove</span>
                <button className="btn btn-ghost" type="button" onClick={() => removeAction(action.id)}>
                  Delete
                </button>
              </label>
            </div>
          ))}
        </div>

        <div className="admin-actions" style={{ marginTop: 16 }}>
          <label className="pill" style={{ gap: 8 }}>
            <input
              type="checkbox"
              checked={draft.dry_run}
              onChange={(event) => setDraft((current) => ({ ...current, dry_run: event.target.checked }))}
            />
            Dry-run mode
          </label>
          <button className="btn btn-primary" type="button" onClick={saveRule}>
            Save rule
          </button>
        </div>
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <div>
            <h2>Preview & test</h2>
            <p className="muted">POST rule payloads to <code>/rules/test</code> before enabling.</p>
          </div>
          <label className="pill" style={{ gap: 8 }}>
            <input type="checkbox" checked={testDryRun} onChange={(event) => setTestDryRun(event.target.checked)} />
            Dry-run test
          </label>
        </div>

        <div className="form-grid">
          <label className="full">
            <span>Test event JSON</span>
            <textarea rows={6} value={testEventJson} onChange={(event) => setTestEventJson(event.target.value)} />
          </label>
        </div>

        <div className="admin-actions" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" type="button" onClick={runTest} disabled={testLoading}>
            {testLoading ? "Testing..." : "Run test"}
          </button>
        </div>

        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="full">
            <span>Rule payload preview</span>
            <pre
              style={{
                margin: 0,
                padding: "12px",
                background: "var(--surface-muted)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(rulePayload, null, 2)}
            </pre>
          </label>
          <label className="full">
            <span>Test response</span>
            <pre
              style={{
                margin: 0,
                padding: "12px",
                background: "var(--surface-muted)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                whiteSpace: "pre-wrap",
                minHeight: "120px",
              }}
            >
              {testResponse ?? "Run a test to see the response."}
            </pre>
          </label>
        </div>
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <div>
            <h2>Runs log</h2>
            <p className="muted">Monitor rule executions, dry-run previews, and failures.</p>
          </div>
          <button className="btn btn-ghost" type="button" onClick={refreshRuns}>
            Refresh
          </button>
        </div>

        {runsStatus ? <p className="alert alert-info">{runsStatus}</p> : null}

        <div className="form-grid" style={{ marginBottom: 12 }}>
          <label>
            <span>Status filter</span>
            <select value={runFilter} onChange={(event) => setRunFilter(event.target.value)}>
              <option value="all">All</option>
              <option value="success">Success</option>
              <option value="skipped">Skipped</option>
              <option value="error">Error</option>
            </select>
          </label>
          <label>
            <span>Rule filter</span>
            <select value={runRuleFilter} onChange={(event) => setRunRuleFilter(event.target.value)}>
              <option value="all">All rules</option>
              {rules.map((rule) => (
                <option key={rule.id} value={rule.id}>
                  {rule.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Dry run</th>
                <th>Duration</th>
                <th>Executed</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {filteredRuns.length ? (
                filteredRuns.map((run) => (
                  <tr key={run.id}>
                    <td>{run.rule_name}</td>
                    <td>{run.trigger}</td>
                    <td>{runStatusPill(run.status)}</td>
                    <td>{run.dry_run ? "Yes" : "No"}</td>
                    <td>{run.duration_ms} ms</td>
                    <td>{formatTimestamp(run.executed_at)}</td>
                    <td>{run.notes}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="muted">
                    No runs match the selected filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
