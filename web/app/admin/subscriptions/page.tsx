"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Subscription = {
  subscription_id: string;
  client_id: string;
  status: string;
  status_reason: string | null;
  frequency: string;
  next_run_at: string;
  preferred_weekday: number | null;
  preferred_day_of_month: number | null;
  base_service_type: string;
  base_price: number;
  created_at: string;
};

type PendingAction = {
  subscriptionId: string;
  action: "pause" | "resume";
};

const FREQUENCY_OPTIONS = [
  { value: "WEEKLY", label: "Weekly" },
  { value: "BIWEEKLY", label: "Biweekly" },
  { value: "MONTHLY", label: "Monthly" },
];

const defaultStartDate = () => new Date().toISOString().split("T")[0];

export default function SubscriptionsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createMessage, setCreateMessage] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [clientEmail, setClientEmail] = useState("");
  const [clientName, setClientName] = useState("");
  const [frequency, setFrequency] = useState("WEEKLY");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [serviceType, setServiceType] = useState("Standard cleaning");
  const [basePrice, setBasePrice] = useState("12000");

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      {
        key: "org-settings",
        label: "Org Settings",
        href: "/admin/settings/org",
        featureKey: "module.settings",
      },
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
      },
      {
        key: "roles",
        label: "Roles & Permissions",
        href: "/admin/iam/roles",
        featureKey: "module.teams",
        requiresPermission: "users.manage",
      },
    ];
    const links = candidates
      .filter((entry) => !entry.requiresPermission || permissionKeys.includes(entry.requiresPermission))
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, requiresPermission, ...link }) => link);
    return [...links, { key: "subscriptions", label: "Subscriptions", href: "/admin/subscriptions" }];
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
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/feature-config`, {
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
    const response = await fetch(`${API_BASE}/v1/admin/ui/prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    }
  }, [authHeaders, password, username]);

  const loadSubscriptions = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/subscriptions`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Failed to load subscriptions (${response.status})`);
      }
      const data = (await response.json()) as Subscription[];
      setSubscriptions(data);
    } catch (err) {
      console.error("Failed to load subscriptions", err);
      setError("Unable to load subscriptions.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, password, username]);

  const createSubscription = useCallback(async () => {
    if (!username || !password) return;
    setCreateLoading(true);
    setCreateError(null);
    setCreateMessage(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/subscriptions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          client_email: clientEmail.trim(),
          client_name: clientName.trim() || null,
          frequency,
          start_date: startDate,
          preferred_weekday: null,
          preferred_day_of_month: frequency === "MONTHLY" ? Number.parseInt(startDate.split("-")[2], 10) : null,
          base_service_type: serviceType.trim(),
          base_price: Number.parseInt(basePrice, 10) || 0,
        }),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Create failed (${response.status}): ${text}`);
      }
      setCreateMessage("Subscription created.");
      setClientEmail("");
      setClientName("");
      setFrequency("WEEKLY");
      setStartDate(defaultStartDate());
      setServiceType("Standard cleaning");
      setBasePrice("12000");
      await loadSubscriptions();
    } catch (err) {
      console.error("Failed to create subscription", err);
      setCreateError("Unable to create subscription.");
    } finally {
      setCreateLoading(false);
    }
  }, [
    authHeaders,
    basePrice,
    clientEmail,
    clientName,
    frequency,
    loadSubscriptions,
    password,
    serviceType,
    startDate,
    username,
  ]);

  const updateSubscriptionStatus = useCallback(
    async (subscriptionId: string, status: "PAUSED" | "ACTIVE") => {
      if (!username || !password) return;
      setActionLoading((prev) => ({ ...prev, [subscriptionId]: true }));
      try {
        const response = await fetch(`${API_BASE}/v1/admin/subscriptions/${subscriptionId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify({
            status,
            status_reason: status === "PAUSED" ? "Paused via admin console" : null,
          }),
        });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(`Update failed (${response.status}): ${text}`);
        }
        setPendingAction(null);
        await loadSubscriptions();
      } catch (err) {
        console.error("Failed to update subscription status", err);
        setError("Unable to update subscription status.");
      } finally {
        setActionLoading((prev) => ({ ...prev, [subscriptionId]: false }));
      }
    },
    [authHeaders, loadSubscriptions, password, username]
  );

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    loadProfile();
    loadFeatureConfig();
    loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    loadSubscriptions();
  }, [loadSubscriptions, password, username]);

  return (
    <div className="admin-page" data-testid="subscriptions-page">
      <header className="admin-header">
        <div>
          <h1 data-testid="subscriptions-title">Subscriptions</h1>
          <p className="muted">Create, pause, and resume subscription plans.</p>
        </div>
      </header>

      <AdminNav links={navLinks} activeKey="subscriptions" />

      <section className="card" data-testid="subscription-create-section">
        <div className="card-header">
          <strong>Create subscription</strong>
        </div>
        <div className="card-body">
          {createError ? <p className="alert alert-warning">{createError}</p> : null}
          {createMessage ? <p className="alert alert-success">{createMessage}</p> : null}
          <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
            <label className="field">
              <span className="label">Client email</span>
              <input
                data-testid="subscription-client-email-input"
                type="email"
                value={clientEmail}
                onChange={(event) => setClientEmail(event.target.value)}
                placeholder="client@example.com"
              />
            </label>
            <label className="field">
              <span className="label">Client name</span>
              <input
                data-testid="subscription-client-name-input"
                type="text"
                value={clientName}
                onChange={(event) => setClientName(event.target.value)}
                placeholder="Optional"
              />
            </label>
            <label className="field">
              <span className="label">Frequency</span>
              <select
                data-testid="subscription-frequency-select"
                value={frequency}
                onChange={(event) => setFrequency(event.target.value)}
              >
                {FREQUENCY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="label">Start date</span>
              <input
                data-testid="subscription-start-date-input"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="label">Service type</span>
              <input
                data-testid="subscription-service-input"
                type="text"
                value={serviceType}
                onChange={(event) => setServiceType(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="label">Base price (cents)</span>
              <input
                data-testid="subscription-price-input"
                type="number"
                min={0}
                value={basePrice}
                onChange={(event) => setBasePrice(event.target.value)}
              />
            </label>
          </div>
          <div className="settings-actions" style={{ marginTop: "12px" }}>
            <button
              className="btn"
              type="button"
              data-testid="subscription-create-btn"
              onClick={createSubscription}
              disabled={createLoading || !clientEmail || !serviceType}
            >
              {createLoading ? "Creating…" : "Create subscription"}
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <strong>Active subscriptions</strong>
        </div>
        <div className="card-body">
          {error ? <p className="alert alert-warning">{error}</p> : null}
          {loading ? <p className="muted">Loading subscriptions…</p> : null}
          {subscriptions.length === 0 && !loading ? <p className="muted">No subscriptions yet.</p> : null}
          {subscriptions.length > 0 ? (
            <div className="table-wrapper">
              <table className="table">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Service</th>
                    <th>Status</th>
                    <th>Frequency</th>
                    <th>Next run</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {subscriptions.map((subscription) => {
                    const isPaused = subscription.status === "PAUSED";
                    const isActive = subscription.status === "ACTIVE";
                    const actionPending = pendingAction?.subscriptionId === subscription.subscription_id;
                    const actionLabel = pendingAction?.action === "pause" ? "Pause" : "Resume";
                    return (
                      <tr
                        key={subscription.subscription_id}
                        data-testid={`subscription-row-${subscription.subscription_id}`}
                      >
                        <td>{subscription.client_id}</td>
                        <td>{subscription.base_service_type}</td>
                        <td>
                          <span data-testid={`subscription-status-${subscription.subscription_id}`}>
                            {subscription.status}
                          </span>
                          {subscription.status_reason ? (
                            <div className="muted small">{subscription.status_reason}</div>
                          ) : null}
                        </td>
                        <td>{subscription.frequency}</td>
                        <td>{new Date(subscription.next_run_at).toLocaleDateString()}</td>
                        <td>
                          {actionPending ? (
                            <div className="stack" style={{ gap: "6px" }}>
                              <button
                                className="btn btn-warning"
                                type="button"
                                data-testid={`subscription-confirm-${pendingAction?.action}-btn-${subscription.subscription_id}`}
                                onClick={() =>
                                  updateSubscriptionStatus(
                                    subscription.subscription_id,
                                    pendingAction?.action === "pause" ? "PAUSED" : "ACTIVE"
                                  )
                                }
                                disabled={actionLoading[subscription.subscription_id]}
                              >
                                Confirm {actionLabel}
                              </button>
                              <button
                                className="btn btn-ghost"
                                type="button"
                                data-testid={`subscription-cancel-action-btn-${subscription.subscription_id}`}
                                onClick={() => setPendingAction(null)}
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <div className="stack" style={{ gap: "6px" }}>
                              {isActive ? (
                                <button
                                  className="btn btn-warning"
                                  type="button"
                                  data-testid={`subscription-pause-btn-${subscription.subscription_id}`}
                                  onClick={() =>
                                    setPendingAction({
                                      subscriptionId: subscription.subscription_id,
                                      action: "pause",
                                    })
                                  }
                                  disabled={actionLoading[subscription.subscription_id]}
                                >
                                  Pause
                                </button>
                              ) : null}
                              {isPaused ? (
                                <button
                                  className="btn btn-ghost"
                                  type="button"
                                  data-testid={`subscription-resume-btn-${subscription.subscription_id}`}
                                  onClick={() =>
                                    setPendingAction({
                                      subscriptionId: subscription.subscription_id,
                                      action: "resume",
                                    })
                                  }
                                  disabled={actionLoading[subscription.subscription_id]}
                                >
                                  Resume
                                </button>
                              ) : null}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
