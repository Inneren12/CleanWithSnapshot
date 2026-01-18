"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  effectiveFeatureEnabled,
  isVisible,
} from "../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type LeadSummary = {
  lead_id: string;
  name: string;
  email?: string | null;
  phone: string;
  status: string;
  created_at: string;
};

type LeadListResponse = {
  items: LeadSummary[];
};

type ScoringCondition = {
  field: string;
  op: string;
  value: string;
};

type ScoringRule = {
  key: string;
  label: string;
  points: number;
  conditions: ScoringCondition[];
};

type ScoringRulesVersion = {
  org_id: string;
  version: number;
  enabled: boolean;
  rules: ScoringRule[];
  created_at: string;
};

type ScoringRulesListResponse = {
  active_version: number | null;
  items: ScoringRulesVersion[];
};

type ScoreReason = {
  rule_key: string;
  label: string;
  points: number;
};

type ScoreSnapshot = {
  org_id: string;
  lead_id: string;
  score: number;
  reasons: ScoreReason[];
  computed_at: string;
  rules_version: number;
};

const EMPTY_RULE: ScoringRule = {
  key: "",
  label: "",
  points: 0,
  conditions: [],
};

const EMPTY_CONDITION: ScoringCondition = {
  field: "",
  op: "equals",
  value: "",
};

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parseConditionValue(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  const numeric = Number(trimmed);
  if (!Number.isNaN(numeric) && String(numeric) === trimmed) return numeric;
  if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
    try {
      return JSON.parse(trimmed) as unknown;
    } catch {
      return trimmed;
    }
  }
  return trimmed;
}

function stringifyConditionValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function formatScore(score: number) {
  return score > 0 ? `+${score}` : `${score}`;
}

export default function LeadsScoringPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [rulesVersion, setRulesVersion] = useState<ScoringRulesVersion | null>(null);
  const [draftEnabled, setDraftEnabled] = useState(true);
  const [draftRules, setDraftRules] = useState<ScoringRule[]>([]);
  const [leads, setLeads] = useState<LeadSummary[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState("");
  const [preview, setPreview] = useState<ScoreSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const scoringVisible = visibilityReady
    ? isVisible("leads.scoring", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const scoringEnabled = featureConfig
    ? effectiveFeatureEnabled(featureOverrides, "module.leads") &&
      effectiveFeatureEnabled(featureOverrides, "leads.scoring")
    : true;

  const canView = permissionKeys.includes("leads.view");
  const canManage = permissionKeys.includes("leads.manage");

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "leads", label: "Leads", href: "/admin/leads", featureKey: "module.leads" },
      {
        key: "leads-nurture",
        label: "Lead Nurture",
        href: "/admin/leads/nurture",
        featureKey: "leads.nurture",
      },
      {
        key: "leads-scoring",
        label: "Lead Scoring",
        href: "/admin/leads/scoring",
        featureKey: "leads.scoring",
      },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
      {
        key: "pricing",
        label: "Service Types & Pricing",
        href: "/admin/settings/pricing",
        featureKey: "module.settings",
      },
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
      },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "module.settings" },
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
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } else {
      setFeatureConfig(null);
      setSettingsError("Failed to load module settings.");
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    } else {
      setUiPrefs(null);
      setSettingsError("Failed to load UI preferences.");
    }
  }, [authHeaders, password, username]);

  const loadRules = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/scoring/rules`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ScoringRulesListResponse;
      const active = data.items.find((item) => item.enabled) ?? data.items[0] ?? null;
      setRulesVersion(active);
      setDraftEnabled(active?.enabled ?? true);
      setDraftRules(
        (active?.rules ?? []).map((rule) => ({
          ...rule,
          conditions: (rule.conditions ?? []).map((condition) => ({
            field: condition.field ?? "",
            op: condition.op ?? "equals",
            value: stringifyConditionValue(condition.value),
          })),
        }))
      );
    } else if (response.status === 403) {
      setError("You do not have permission to view scoring rules.");
    } else {
      setError("Failed to load scoring rules.");
    }
    setLoading(false);
  }, [authHeaders, password, username]);

  const loadLeads = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/leads?page=1`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as LeadListResponse;
      setLeads(data.items);
      if (!selectedLeadId && data.items.length > 0) {
        setSelectedLeadId(data.items[0]?.lead_id ?? "");
      }
    }
  }, [authHeaders, password, selectedLeadId, username]);

  const handleRuleChange = useCallback((index: number, updates: Partial<ScoringRule>) => {
    setDraftRules((prev) => prev.map((rule, idx) => (idx === index ? { ...rule, ...updates } : rule)));
  }, []);

  const handleConditionChange = useCallback(
    (ruleIndex: number, conditionIndex: number, updates: Partial<ScoringCondition>) => {
      setDraftRules((prev) =>
        prev.map((rule, idx) => {
          if (idx !== ruleIndex) return rule;
          const nextConditions = rule.conditions.map((condition, cIdx) =>
            cIdx === conditionIndex ? { ...condition, ...updates } : condition
          );
          return { ...rule, conditions: nextConditions };
        })
      );
    },
    []
  );

  const addCondition = useCallback((ruleIndex: number) => {
    setDraftRules((prev) =>
      prev.map((rule, idx) =>
        idx === ruleIndex
          ? { ...rule, conditions: [...rule.conditions, { ...EMPTY_CONDITION }] }
          : rule
      )
    );
  }, []);

  const removeCondition = useCallback((ruleIndex: number, conditionIndex: number) => {
    setDraftRules((prev) =>
      prev.map((rule, idx) => {
        if (idx !== ruleIndex) return rule;
        const nextConditions = rule.conditions.filter((_, cIdx) => cIdx !== conditionIndex);
        return { ...rule, conditions: nextConditions };
      })
    );
  }, []);

  const addRule = useCallback(() => {
    setDraftRules((prev) => [...prev, { ...EMPTY_RULE, conditions: [{ ...EMPTY_CONDITION }] }]);
  }, []);

  const removeRule = useCallback((index: number) => {
    setDraftRules((prev) => prev.filter((_, idx) => idx !== index));
  }, []);

  const resetDraft = useCallback(() => {
    setDraftEnabled(rulesVersion?.enabled ?? true);
    setDraftRules(
      (rulesVersion?.rules ?? []).map((rule) => ({
        ...rule,
        conditions: (rule.conditions ?? []).map((condition) => ({
          field: condition.field ?? "",
          op: condition.op ?? "equals",
          value: stringifyConditionValue(condition.value),
        })),
      }))
    );
    setSaveMessage(null);
  }, [rulesVersion]);

  const saveRules = useCallback(async () => {
    if (!username || !password) return;
    setSaving(true);
    setSaveMessage(null);
    setError(null);
    const payload = {
      enabled: draftEnabled,
      rules: draftRules.map((rule) => ({
        key: rule.key.trim(),
        label: rule.label.trim(),
        points: Number(rule.points) || 0,
        conditions: rule.conditions
          .filter((condition) => condition.field.trim())
          .map((condition) => ({
            field: condition.field.trim(),
            op: condition.op.trim() || "equals",
            value: parseConditionValue(condition.value),
          })),
      })),
    };

    const response = await fetch(`${API_BASE}/v1/admin/leads/scoring/rules`, {
      method: "PATCH",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      const data = (await response.json()) as ScoringRulesVersion;
      setRulesVersion(data);
      setSaveMessage("Scoring rules saved.");
      setDraftEnabled(data.enabled);
      setDraftRules(
        data.rules.map((rule) => ({
          ...rule,
          conditions: rule.conditions.map((condition) => ({
            field: condition.field ?? "",
            op: condition.op ?? "equals",
            value: stringifyConditionValue(condition.value),
          })),
        }))
      );
    } else if (response.status === 403) {
      setError("You do not have permission to update scoring rules.");
    } else {
      setError("Failed to update scoring rules.");
    }
    setSaving(false);
  }, [authHeaders, draftEnabled, draftRules, password, username]);

  const runPreview = useCallback(async () => {
    if (!username || !password || !selectedLeadId) return;
    setPreviewLoading(true);
    setPreviewError(null);
    setPreview(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${selectedLeadId}/scoring/recompute`, {
      method: "POST",
      headers: authHeaders,
    });
    if (response.ok) {
      const data = (await response.json()) as ScoreSnapshot;
      setPreview(data);
    } else if (response.status === 404) {
      setPreviewError("Lead or scoring rules not found.");
    } else if (response.status === 403) {
      setPreviewError("You do not have permission to recompute lead scores.");
    } else {
      setPreviewError("Failed to recompute lead score.");
    }
    setPreviewLoading(false);
  }, [authHeaders, password, selectedLeadId, username]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    void loadFeatureConfig();
  }, [loadFeatureConfig]);

  useEffect(() => {
    void loadUiPrefs();
  }, [loadUiPrefs]);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  useEffect(() => {
    void loadLeads();
  }, [loadLeads]);

  const hasRules = draftRules.length > 0;
  const reasonsPreview = preview?.reasons ?? [];

  return (
    <div className="page">
      <AdminNav links={navLinks} activeKey="leads-scoring" />
      <section className="admin-card admin-section">
        <div className="section-heading">
          <h1>Lead Scoring</h1>
          <p className="muted">Define deterministic scoring rules and preview them against a lead.</p>
        </div>
        {settingsError ? <p className="alert alert-error">{settingsError}</p> : null}
        {!scoringVisible ? (
          <p className="alert alert-warning">Lead scoring is hidden for your profile.</p>
        ) : null}
        {!scoringEnabled ? (
          <p className="alert alert-warning">Coming soon / disabled. Enable lead scoring in Modules &amp; Visibility.</p>
        ) : null}
        {loading ? <p className="muted">Loading scoring rules...</p> : null}
        {error ? <p className="alert alert-error">{error}</p> : null}
        {rulesVersion ? (
          <div className="admin-actions" style={{ marginTop: "12px", flexWrap: "wrap" }}>
            <div>
              <span className="label">Active version</span>
              <div>v{rulesVersion.version}</div>
            </div>
            <div>
              <span className="label">Last updated</span>
              <div>{formatDateTime(rulesVersion.created_at)}</div>
            </div>
            <div>
              <span className="label">Rules enabled</span>
              <div>{rulesVersion.enabled ? "Enabled" : "Disabled"}</div>
            </div>
          </div>
        ) : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>Rules editor</h2>
          <p className="muted">Assign points to lead attributes and behaviors.</p>
        </div>
        {!scoringEnabled ? <p className="muted">Rules editor is disabled while lead scoring is turned off.</p> : null}
        <div className="admin-actions" style={{ flexWrap: "wrap", alignItems: "center" }}>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={draftEnabled}
              onChange={(event) => setDraftEnabled(event.target.checked)}
              disabled={!scoringEnabled || !canManage}
            />
            <span>Enable scoring rules</span>
          </label>
          <button className="btn btn-secondary" onClick={addRule} disabled={!scoringEnabled || !canManage}>
            Add rule
          </button>
          <button className="btn btn-secondary" onClick={resetDraft} disabled={!canManage}>
            Reset changes
          </button>
          <button className="btn btn-primary" onClick={saveRules} disabled={!scoringEnabled || !canManage || saving}>
            {saving ? "Saving..." : "Save rules"}
          </button>
        </div>
        {saveMessage ? <p className="alert alert-success">{saveMessage}</p> : null}
        {!hasRules ? <p className="muted">No rules configured yet.</p> : null}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {draftRules.map((rule, index) => (
            <div key={`${rule.key}-${index}`} className="admin-card" style={{ padding: "16px" }}>
              <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
                <label>
                  <span className="label">Rule key</span>
                  <input
                    type="text"
                    value={rule.key}
                    onChange={(event) => handleRuleChange(index, { key: event.target.value })}
                    disabled={!scoringEnabled || !canManage}
                  />
                </label>
                <label>
                  <span className="label">Label</span>
                  <input
                    type="text"
                    value={rule.label}
                    onChange={(event) => handleRuleChange(index, { label: event.target.value })}
                    disabled={!scoringEnabled || !canManage}
                  />
                </label>
                <label>
                  <span className="label">Points</span>
                  <input
                    type="number"
                    value={rule.points}
                    onChange={(event) => handleRuleChange(index, { points: Number(event.target.value) })}
                    disabled={!scoringEnabled || !canManage}
                  />
                </label>
                <div style={{ display: "flex", alignItems: "flex-end", gap: "8px" }}>
                  <button className="btn btn-secondary" onClick={() => addCondition(index)} disabled={!canManage}>
                    Add condition
                  </button>
                  <button className="btn btn-secondary" onClick={() => removeRule(index)} disabled={!canManage}>
                    Remove rule
                  </button>
                </div>
              </div>
              <div style={{ marginTop: "12px" }}>
                <span className="label">Conditions</span>
                {rule.conditions.length === 0 ? <p className="muted">No conditions (applies to all leads).</p> : null}
                <div style={{ display: "grid", gap: "8px", marginTop: "8px" }}>
                  {rule.conditions.map((condition, conditionIndex) => (
                    <div
                      key={`${condition.field}-${conditionIndex}`}
                      className="admin-grid"
                      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}
                    >
                      <label>
                        <span className="label">Field</span>
                        <input
                          type="text"
                          value={condition.field}
                          onChange={(event) =>
                            handleConditionChange(index, conditionIndex, { field: event.target.value })
                          }
                          disabled={!scoringEnabled || !canManage}
                        />
                      </label>
                      <label>
                        <span className="label">Operator</span>
                        <select
                          value={condition.op}
                          onChange={(event) =>
                            handleConditionChange(index, conditionIndex, { op: event.target.value })
                          }
                          disabled={!scoringEnabled || !canManage}
                        >
                          <option value="equals">equals</option>
                          <option value="not_equals">not equals</option>
                          <option value="contains">contains</option>
                          <option value="greater_than">greater than</option>
                          <option value="less_than">less than</option>
                          <option value="exists">exists</option>
                          <option value="in">in</option>
                        </select>
                      </label>
                      <label>
                        <span className="label">Value</span>
                        <input
                          type="text"
                          value={condition.value}
                          onChange={(event) =>
                            handleConditionChange(index, conditionIndex, { value: event.target.value })
                          }
                          placeholder='e.g. 3, true, "google"'
                          disabled={!scoringEnabled || !canManage}
                        />
                      </label>
                      <div style={{ display: "flex", alignItems: "flex-end" }}>
                        <button
                          className="btn btn-secondary"
                          onClick={() => removeCondition(index, conditionIndex)}
                          disabled={!canManage}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>Preview score</h2>
          <p className="muted">Recompute the score for a lead using the active rules.</p>
        </div>
        {!scoringEnabled ? <p className="muted">Preview is disabled while lead scoring is turned off.</p> : null}
        <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <label>
            <span className="label">Lead</span>
            <select
              value={selectedLeadId}
              onChange={(event) => setSelectedLeadId(event.target.value)}
              disabled={!scoringEnabled || !canManage}
            >
              {leads.map((lead) => (
                <option key={lead.lead_id} value={lead.lead_id}>
                  {lead.name} • {lead.status}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="label">Lead ID</span>
            <input
              type="text"
              value={selectedLeadId}
              onChange={(event) => setSelectedLeadId(event.target.value)}
              placeholder="Paste lead ID"
              disabled={!scoringEnabled || !canManage}
            />
          </label>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button className="btn btn-primary" onClick={runPreview} disabled={!scoringEnabled || !canManage}>
              {previewLoading ? "Computing..." : "Preview score"}
            </button>
          </div>
        </div>
        {!canManage ? <p className="muted">You need leads.manage to recompute scores.</p> : null}
        {previewError ? <p className="alert alert-error">{previewError}</p> : null}
        {preview ? (
          <div className="admin-card" style={{ marginTop: "16px", padding: "16px" }}>
            <div className="admin-actions" style={{ flexWrap: "wrap" }}>
              <div>
                <span className="label">Score</span>
                <div className="status-badge ok" style={{ display: "inline-flex", marginTop: "4px" }}>
                  {formatScore(preview.score)}
                </div>
              </div>
              <div>
                <span className="label">Rules version</span>
                <div>v{preview.rules_version}</div>
              </div>
              <div>
                <span className="label">Computed</span>
                <div>{formatDateTime(preview.computed_at)}</div>
              </div>
            </div>
            <div style={{ marginTop: "12px" }}>
              <span className="label">Top reasons</span>
              {reasonsPreview.length === 0 ? (
                <p className="muted">No matching rules for this lead.</p>
              ) : (
                <ul className="clean-list" style={{ marginTop: "8px" }}>
                  {reasonsPreview.map((reason) => (
                    <li key={`${reason.rule_key}-${reason.label}`}>
                      <strong>{formatScore(reason.points)}</strong> {reason.label}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : null}
        {!canView ? <p className="muted">You need leads.view to access scoring rules.</p> : null}
      </section>
    </div>
  );
}
