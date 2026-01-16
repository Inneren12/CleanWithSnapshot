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

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

type RecurringSeries = {
  series_id: string;
  org_id: string;
  client_id: string | null;
  address_id: number | null;
  service_type_id: number | null;
  preferred_team_id: number | null;
  preferred_worker_id: number | null;
  status: "active" | "paused" | "cancelled";
  starts_on: string;
  start_time: string;
  frequency: "weekly" | "monthly";
  interval: number;
  by_weekday: number[];
  by_monthday: number[];
  ends_on: string | null;
  duration_minutes: number;
  horizon_days: number;
  next_run_at: string | null;
  next_occurrence_local: string | null;
  created_at: string;
  updated_at: string;
  created_count: number;
  client_label: string | null;
  address_label: string | null;
  service_type_label: string | null;
  team_label: string | null;
  worker_label: string | null;
};

type RecurringSeriesListResponse = {
  org_timezone: string;
  items: RecurringSeries[];
};

type ServiceTypeOption = {
  service_type_id: number;
  name: string;
  active: boolean;
};

type GenerationReport = {
  org_timezone: string;
  horizon_end: string;
  next_run_at: string | null;
  created: { scheduled_for: string; booking_id: string | null; reason: string | null }[];
  needs_assignment: { scheduled_for: string; booking_id: string | null; reason: string | null }[];
  skipped: { scheduled_for: string; booking_id: string | null; reason: string | null }[];
  conflicted: { scheduled_for: string; booking_id: string | null; reason: string | null }[];
};

function formatOccurrence(value: string | null, timeZone: string) {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleString("en-CA", {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function parseMonthdays(value: string) {
  return value
    .split(",")
    .map((chunk) => Number(chunk.trim()))
    .filter((chunk) => Number.isFinite(chunk) && chunk > 0);
}

function monthdayLabel(value: number[]) {
  return value.length ? value.join(", ") : "—";
}

export default function RecurringSeriesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [orgTimezone, setOrgTimezone] = useState("UTC");
  const [series, setSeries] = useState<RecurringSeries[]>([]);
  const [serviceTypes, setServiceTypes] = useState<ServiceTypeOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<GenerationReport | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [formClientId, setFormClientId] = useState("");
  const [formAddressId, setFormAddressId] = useState("");
  const [formServiceTypeId, setFormServiceTypeId] = useState("");
  const [formTeamId, setFormTeamId] = useState("");
  const [formWorkerId, setFormWorkerId] = useState("");
  const [formStatus, setFormStatus] = useState<RecurringSeries["status"]>("active");
  const [formStartsOn, setFormStartsOn] = useState("");
  const [formStartTime, setFormStartTime] = useState("09:00");
  const [formFrequency, setFormFrequency] = useState<RecurringSeries["frequency"]>("weekly");
  const [formInterval, setFormInterval] = useState("1");
  const [formByWeekday, setFormByWeekday] = useState<number[]>([]);
  const [formByMonthday, setFormByMonthday] = useState("");
  const [formEndsOn, setFormEndsOn] = useState("");
  const [formDuration, setFormDuration] = useState("120");
  const [formHorizon, setFormHorizon] = useState("60");
  const [formError, setFormError] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const isAuthenticated = Boolean(username && password);
  const permissionKeys = profile?.permissions ?? [];
  const canManage = permissionKeys.includes("bookings.edit");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("module.schedule", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "recurring", label: "Recurring", href: "/admin/schedule/recurring", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
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
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
        featureKey: "module.settings",
      },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
      { key: "roles", label: "Roles & Permissions", href: "/admin/iam/roles", featureKey: "module.teams" },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
  }, [featureOverrides, hiddenKeys, permissionKeys, profile, visibilityReady]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    Promise.all([
      fetch(`${API_BASE}/v1/admin/profile`, { headers: authHeaders }),
      fetch(`${API_BASE}/v1/admin/features`, { headers: authHeaders }),
      fetch(`${API_BASE}/v1/admin/ui-prefs`, { headers: authHeaders }),
    ])
      .then(async ([profileRes, featuresRes, prefsRes]) => {
        if (!profileRes.ok) throw new Error("Failed to load profile");
        if (!featuresRes.ok) throw new Error("Failed to load feature flags");
        if (!prefsRes.ok) throw new Error("Failed to load UI prefs");
        const [profilePayload, featuresPayload, prefsPayload] = await Promise.all([
          profileRes.json(),
          featuresRes.json(),
          prefsRes.json(),
        ]);
        setProfile(profilePayload as AdminProfile);
        setFeatureConfig(featuresPayload as FeatureConfigResponse);
        setUiPrefs(prefsPayload as UiPrefsResponse);
      })
      .catch((fetchError) => {
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load profile");
      });
  }, [authHeaders, isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;
    fetch(`${API_BASE}/v1/admin/service-types`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Failed to load service types");
        return response.json();
      })
      .then((payload: ServiceTypeOption[]) => {
        setServiceTypes(payload.filter((service) => service.active));
      })
      .catch(() => setServiceTypes([]));
  }, [authHeaders, isAuthenticated]);

  const loadSeries = useCallback(() => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/v1/admin/recurring-series`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load recurring series");
        }
        return response.json();
      })
      .then((payload: RecurringSeriesListResponse) => {
        setOrgTimezone(payload.org_timezone);
        setSeries(payload.items ?? []);
      })
      .catch((fetchError) => {
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load recurring series");
      })
      .finally(() => setLoading(false));
  }, [authHeaders, isAuthenticated]);

  useEffect(() => {
    if (!pageVisible) return;
    loadSeries();
  }, [loadSeries, pageVisible]);

  const resetForm = useCallback(() => {
    setEditingId(null);
    setFormClientId("");
    setFormAddressId("");
    setFormServiceTypeId("");
    setFormTeamId("");
    setFormWorkerId("");
    setFormStatus("active");
    setFormStartsOn("");
    setFormStartTime("09:00");
    setFormFrequency("weekly");
    setFormInterval("1");
    setFormByWeekday([]);
    setFormByMonthday("");
    setFormEndsOn("");
    setFormDuration("120");
    setFormHorizon("60");
    setFormError(null);
  }, []);

  const handleEdit = useCallback((item: RecurringSeries) => {
    setEditingId(item.series_id);
    setFormClientId(item.client_id ?? "");
    setFormAddressId(item.address_id ? String(item.address_id) : "");
    setFormServiceTypeId(item.service_type_id ? String(item.service_type_id) : "");
    setFormTeamId(item.preferred_team_id ? String(item.preferred_team_id) : "");
    setFormWorkerId(item.preferred_worker_id ? String(item.preferred_worker_id) : "");
    setFormStatus(item.status);
    setFormStartsOn(item.starts_on);
    setFormStartTime(item.start_time.slice(0, 5));
    setFormFrequency(item.frequency);
    setFormInterval(String(item.interval));
    setFormByWeekday(item.by_weekday ?? []);
    setFormByMonthday(item.by_monthday?.length ? item.by_monthday.join(", ") : "");
    setFormEndsOn(item.ends_on ?? "");
    setFormDuration(String(item.duration_minutes));
    setFormHorizon(String(item.horizon_days));
    setFormError(null);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!canManage) return;
    setFormError(null);
    const interval = Number(formInterval);
    const duration = Number(formDuration);
    const horizon = Number(formHorizon);
    if (!formStartsOn || !formStartTime || !interval || !duration || !horizon) {
      setFormError("Provide start date/time, interval, duration, and horizon.");
      return;
    }
    const payload = {
      client_id: formClientId.trim() ? formClientId.trim() : null,
      address_id: formAddressId.trim() ? Number(formAddressId) : null,
      service_type_id: formServiceTypeId.trim() ? Number(formServiceTypeId) : null,
      preferred_team_id: formTeamId.trim() ? Number(formTeamId) : null,
      preferred_worker_id: formWorkerId.trim() ? Number(formWorkerId) : null,
      status: formStatus,
      starts_on: formStartsOn,
      start_time: `${formStartTime}:00`,
      frequency: formFrequency,
      interval,
      by_weekday: formByWeekday,
      by_monthday: formByMonthday.trim() ? parseMonthdays(formByMonthday) : [],
      ends_on: formEndsOn.trim() ? formEndsOn : null,
      duration_minutes: duration,
      horizon_days: horizon,
    };
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/recurring-series${editingId ? `/${editingId}` : ""}`,
        {
          method: editingId ? "PATCH" : "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "Save failed");
      }
      resetForm();
      setReport(null);
      loadSeries();
    } catch (fetchError) {
      setFormError(fetchError instanceof Error ? fetchError.message : "Save failed");
    }
  }, [
    authHeaders,
    canManage,
    editingId,
    formAddressId,
    formByMonthday,
    formByWeekday,
    formClientId,
    formDuration,
    formEndsOn,
    formFrequency,
    formHorizon,
    formInterval,
    formServiceTypeId,
    formStartTime,
    formStartsOn,
    formStatus,
    formTeamId,
    formWorkerId,
    loadSeries,
    resetForm,
  ]);

  const handleGenerate = useCallback(
    async (seriesId: string) => {
      if (!canManage) return;
      setReport(null);
      try {
        const response = await fetch(`${API_BASE}/v1/admin/recurring-series/${seriesId}/generate`, {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({}),
        });
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Generation failed");
        }
        const payload = (await response.json()) as GenerationReport;
        setReport(payload);
        loadSeries();
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : "Generation failed");
      }
    },
    [authHeaders, canManage, loadSeries]
  );

  const handleStatusChange = useCallback(
    async (seriesId: string, status: RecurringSeries["status"]) => {
      if (!canManage) return;
      setError(null);
      try {
        const response = await fetch(`${API_BASE}/v1/admin/recurring-series/${seriesId}`, {
          method: "PATCH",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status }),
        });
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Update failed");
        }
        loadSeries();
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : "Update failed");
      }
    },
    [authHeaders, canManage, loadSeries]
  );

  if (visibilityReady && !pageVisible) {
    return (
      <div className="schedule-page">
        <AdminNav links={navLinks} activeKey="recurring" />
        <section className="card">
          <div className="card-body">
            <h1>Recurring Series</h1>
            <p className="muted">Schedule module access is disabled for your role.</p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="schedule-page">
      <AdminNav links={navLinks} activeKey="recurring" />
      <header className="schedule-header">
        <div>
          <h1>Recurring Series</h1>
          <p className="muted">Plan repeating bookings and generate upcoming work orders.</p>
        </div>
      </header>

      <section className="card">
        <div className="card-body">
          <div className="schedule-auth">
            <div className="schedule-auth-fields">
              <input
                className="input"
                type="text"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin"
              />
              <input
                className="input"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="password"
              />
            </div>
            <div className="schedule-auth-actions">
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => {
                  if (username && password) {
                    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
                    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
                  }
                }}
              >
                Save Credentials
              </button>
            </div>
          </div>
          {error ? <p className="muted">{error}</p> : null}
        </div>
      </section>

      <section className="card">
        <div className="card-body">
          <h2>{editingId ? "Edit series" : "Create series"}</h2>
          {formError ? <p className="muted">{formError}</p> : null}
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px" }}>
            <label className="stack">
              <span className="muted">Client ID</span>
              <input className="input" value={formClientId} onChange={(e) => setFormClientId(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Address ID</span>
              <input className="input" value={formAddressId} onChange={(e) => setFormAddressId(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Service type</span>
              <select
                className="input"
                value={formServiceTypeId}
                onChange={(e) => setFormServiceTypeId(e.target.value)}
              >
                <option value="">Select service</option>
                {serviceTypes.map((service) => (
                  <option key={service.service_type_id} value={service.service_type_id}>
                    {service.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="stack">
              <span className="muted">Preferred team ID</span>
              <input className="input" value={formTeamId} onChange={(e) => setFormTeamId(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Preferred worker ID</span>
              <input className="input" value={formWorkerId} onChange={(e) => setFormWorkerId(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Status</span>
              <select className="input" value={formStatus} onChange={(e) => setFormStatus(e.target.value as RecurringSeries["status"])}>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </label>
            <label className="stack">
              <span className="muted">Start date</span>
              <input className="input" type="date" value={formStartsOn} onChange={(e) => setFormStartsOn(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Start time</span>
              <input className="input" type="time" value={formStartTime} onChange={(e) => setFormStartTime(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Frequency</span>
              <select className="input" value={formFrequency} onChange={(e) => setFormFrequency(e.target.value as RecurringSeries["frequency"])}>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </label>
            <label className="stack">
              <span className="muted">Interval</span>
              <input className="input" type="number" min={1} value={formInterval} onChange={(e) => setFormInterval(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Duration (minutes)</span>
              <input className="input" type="number" min={30} value={formDuration} onChange={(e) => setFormDuration(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Horizon (days)</span>
              <input className="input" type="number" min={1} value={formHorizon} onChange={(e) => setFormHorizon(e.target.value)} />
            </label>
            <label className="stack">
              <span className="muted">Ends on</span>
              <input className="input" type="date" value={formEndsOn} onChange={(e) => setFormEndsOn(e.target.value)} />
            </label>
          </div>
          <div className="stack" style={{ marginTop: "16px" }}>
            <span className="muted">Weekdays</span>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(80px, 1fr))", gap: "8px" }}>
              {WEEKDAYS.map((label, index) => {
                const isActive = formByWeekday.includes(index);
                return (
                  <button
                    key={label}
                    type="button"
                    className={`btn small ${isActive ? "btn-primary" : "secondary"}`}
                    onClick={() => {
                      setFormByWeekday((prev) =>
                        prev.includes(index) ? prev.filter((day) => day !== index) : [...prev, index]
                      );
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
          <label className="stack" style={{ marginTop: "16px" }}>
            <span className="muted">Month days (comma-separated)</span>
            <input className="input" value={formByMonthday} onChange={(e) => setFormByMonthday(e.target.value)} />
          </label>
          <div style={{ marginTop: "16px", display: "flex", gap: "12px", flexWrap: "wrap" }}>
            <button className="btn btn-primary" type="button" onClick={handleSubmit} disabled={!canManage}>
              {editingId ? "Save changes" : "Create series"}
            </button>
            {editingId ? (
              <button className="btn secondary" type="button" onClick={resetForm}>
                Cancel edit
              </button>
            ) : null}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-body">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2>Series list</h2>
            <button className="btn secondary" type="button" onClick={loadSeries}>
              Refresh
            </button>
          </div>
          {loading ? <p className="muted">Loading…</p> : null}
          {!series.length && !loading ? <p className="muted">No recurring series yet.</p> : null}
          {series.length ? (
            <div className="table-wrapper" style={{ marginTop: "12px" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Service</th>
                    <th>Schedule</th>
                    <th>Next occurrence</th>
                    <th>Created</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {series.map((item) => (
                    <tr key={item.series_id}>
                      <td>
                        <div>{item.client_label ?? item.client_id ?? "—"}</div>
                        <div className="muted">{item.address_label ?? item.address_id ?? ""}</div>
                      </td>
                      <td>
                        <div>{item.service_type_label ?? item.service_type_id ?? "—"}</div>
                        <div className="muted">Team {item.team_label ?? item.preferred_team_id ?? "—"}</div>
                      </td>
                      <td>
                        <div>
                          {item.frequency} · every {item.interval}
                        </div>
                        <div className="muted">
                          {item.by_weekday.length ? item.by_weekday.map((day) => WEEKDAYS[day]).join(", ") : "—"}
                          {item.frequency === "monthly" ? ` · ${monthdayLabel(item.by_monthday)}` : ""}
                        </div>
                      </td>
                      <td>
                        <div>{formatOccurrence(item.next_occurrence_local, orgTimezone)}</div>
                        <div className="muted">{orgTimezone}</div>
                      </td>
                      <td>{item.created_count}</td>
                      <td>{item.status}</td>
                      <td>
                        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                          <button className="btn small" type="button" onClick={() => handleEdit(item)}>
                            Edit
                          </button>
                          <button
                            className="btn small"
                            type="button"
                            onClick={() => handleGenerate(item.series_id)}
                            disabled={!canManage}
                          >
                            Generate
                          </button>
                          <button
                            className="btn small"
                            type="button"
                            onClick={() => handleStatusChange(item.series_id, "paused")}
                            disabled={!canManage || item.status === "paused"}
                          >
                            Pause
                          </button>
                          <button
                            className="btn small danger"
                            type="button"
                            onClick={() => handleStatusChange(item.series_id, "cancelled")}
                            disabled={!canManage || item.status === "cancelled"}
                          >
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </section>

      {report ? (
        <section className="card">
          <div className="card-body">
            <h2>Latest generation report</h2>
            <p className="muted">
              Horizon end {formatOccurrence(report.horizon_end, report.org_timezone)} · Next run{" "}
              {formatOccurrence(report.next_run_at, report.org_timezone)}
            </p>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px" }}>
              <div>
                <strong>Created</strong>
                <div className="muted">{report.created.length}</div>
              </div>
              <div>
                <strong>Needs assignment</strong>
                <div className="muted">{report.needs_assignment.length}</div>
              </div>
              <div>
                <strong>Skipped</strong>
                <div className="muted">{report.skipped.length}</div>
              </div>
              <div>
                <strong>Conflicted</strong>
                <div className="muted">{report.conflicted.length}</div>
              </div>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
