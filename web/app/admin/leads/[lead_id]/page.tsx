"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

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

type TimelineEvent = {
  event_id: string;
  event_type: string;
  timestamp: string;
  actor?: string | null;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
};

type LeadDetail = {
  lead_id: string;
  name: string;
  email?: string | null;
  phone: string;
  postal_code?: string | null;
  address?: string | null;
  preferred_dates: string[];
  notes?: string | null;
  loss_reason?: string | null;
  access_notes?: string | null;
  parking?: string | null;
  pets?: string | null;
  allergies?: string | null;
  source?: string | null;
  campaign?: string | null;
  keyword?: string | null;
  landing_page?: string | null;
  created_at: string;
  updated_at: string;
  referrer?: string | null;
  status: string;
  referral_code: string;
  referred_by_code?: string | null;
  referral_credits: number;
  structured_inputs: Record<string, unknown>;
  estimate_snapshot: Record<string, unknown>;
  pricing_config_version: string;
  timeline: TimelineEvent[];
};

type LeadQuoteFollowUp = {
  followup_id: string;
  note: string;
  created_at: string;
  created_by?: string | null;
};

type LeadQuote = {
  quote_id: string;
  lead_id: string;
  amount: number;
  currency: string;
  service_type?: string | null;
  status: string;
  expires_at?: string | null;
  sent_at?: string | null;
  created_at: string;
  updated_at: string;
  followups: LeadQuoteFollowUp[];
};

const ACTIVITY_OPTIONS = [
  { value: "Contacted", label: "Contacted" },
  { value: "Quote sent", label: "Quote sent" },
  { value: "Won", label: "Won" },
  { value: "Lost", label: "Lost" },
  { value: "Note", label: "Note" },
];

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatCurrency(value: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(value);
}

function pickEstimateTotal(snapshot: Record<string, unknown>): number | null {
  const candidates = ["total_before_tax", "total_cents", "total", "price_cents", "subtotal_cents"];
  for (const key of candidates) {
    const raw = snapshot[key];
    if (raw === null || raw === undefined) continue;
    const parsed = Number(raw);
    if (Number.isNaN(parsed)) continue;
    if (key.endsWith("_cents")) {
      return parsed / 100;
    }
    return parsed;
  }
  return null;
}

function stringifyAddOns(addOns: unknown): string {
  if (!addOns || typeof addOns !== "object") return "None";
  const entries = Object.entries(addOns as Record<string, unknown>).filter(([, value]) => {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value > 0;
    return Boolean(value);
  });
  if (!entries.length) return "None";
  return entries.map(([key, value]) => `${key}: ${value}`).join(", ");
}

export default function LeadDetailPage() {
  const params = useParams();
  const leadId = params.lead_id as string;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [quotes, setQuotes] = useState<LeadQuote[]>([]);
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [quotesError, setQuotesError] = useState<string | null>(null);
  const [quoteAmount, setQuoteAmount] = useState("");
  const [quoteCurrency, setQuoteCurrency] = useState("CAD");
  const [quoteServiceType, setQuoteServiceType] = useState("");
  const [quoteExpiresAt, setQuoteExpiresAt] = useState("");
  const [quoteStatus, setQuoteStatus] = useState<string | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [followupNotes, setFollowupNotes] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState(ACTIVITY_OPTIONS[0]?.value ?? "Contacted");
  const [activityNote, setActivityNote] = useState("");
  const [activityStatus, setActivityStatus] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const permissionKeys = profile?.permissions ?? [];
  const canEditLeads =
    permissionKeys.includes("contacts.edit") || permissionKeys.includes("leads.edit");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const scheduleVisible = visibilityReady
    ? isVisible("module.schedule", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "leads", label: "Leads", href: "/admin/leads", featureKey: "module.leads" },
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
      { key: "pricing", label: "Service Types & Pricing", href: "/admin/settings/pricing", featureKey: "module.settings" },
      {
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
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
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } else {
      setFeatureConfig(null);
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
    } else {
      setUiPrefs(null);
    }
  }, [authHeaders, password, username]);

  const loadLead = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as LeadDetail;
      setLead(data);
    } else if (response.status === 403) {
      setError("You do not have permission to view this lead.");
      setLead(null);
    } else if (response.status === 404) {
      setError("Lead not found.");
      setLead(null);
    } else {
      setError("Failed to load lead.");
      setLead(null);
    }
    setLoading(false);
  }, [authHeaders, leadId, password, username]);

  const loadQuotes = useCallback(async () => {
    if (!username || !password) return;
    setQuotesLoading(true);
    setQuotesError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/quotes`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as { items: LeadQuote[] };
      setQuotes(data.items ?? []);
    } else if (response.status === 403) {
      setQuotesError("You do not have permission to view quotes.");
      setQuotes([]);
    } else {
      setQuotesError("Failed to load quotes.");
      setQuotes([]);
    }
    setQuotesLoading(false);
  }, [authHeaders, leadId, password, username]);

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
    void loadUiPrefs();
  }, [loadFeatureConfig, loadUiPrefs]);

  useEffect(() => {
    void loadLead();
  }, [loadLead]);

  useEffect(() => {
    void loadQuotes();
  }, [loadQuotes]);

  const handleActivitySubmit = async () => {
    if (!canEditLeads) {
      setActivityError("Read-only role cannot add timeline events.");
      return;
    }
    setActivityStatus(null);
    setActivityError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/timeline`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ action: activity, note: activityNote || undefined }),
    });
    if (response.ok) {
      setActivityStatus("Activity logged.");
      setActivityNote("");
      void loadLead();
    } else {
      setActivityError("Failed to add timeline entry.");
    }
  };

  const handleQuoteCreate = async (status: "DRAFT" | "SENT") => {
    if (!canEditLeads) {
      setQuoteError("Read-only role cannot create quotes.");
      return;
    }
    setQuoteStatus(null);
    setQuoteError(null);
    const amountValue = Number(quoteAmount);
    if (!quoteAmount || Number.isNaN(amountValue) || amountValue < 0) {
      setQuoteError("Enter a valid quote amount.");
      return;
    }
    const payload: Record<string, unknown> = {
      amount: Math.round(amountValue * 100),
      currency: quoteCurrency || "CAD",
      status,
    };
    if (quoteServiceType.trim()) payload.service_type = quoteServiceType.trim();
    if (quoteExpiresAt) payload.expires_at = new Date(quoteExpiresAt).toISOString();
    if (status === "SENT") payload.sent_at = new Date().toISOString();

    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/quotes`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      setQuoteStatus(status === "SENT" ? "Quote logged as sent." : "Draft quote created.");
      setQuoteAmount("");
      setQuoteServiceType("");
      setQuoteExpiresAt("");
      void loadQuotes();
    } else {
      setQuoteError("Failed to create quote.");
    }
  };

  const handleFollowupSubmit = async (quoteId: string) => {
    if (!canEditLeads) {
      setQuoteError("Read-only role cannot log follow-ups.");
      return;
    }
    const note = followupNotes[quoteId]?.trim();
    if (!note) {
      setQuoteError("Follow-up note cannot be empty.");
      return;
    }
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/quotes/${quoteId}/followups`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    if (response.ok) {
      setQuoteStatus("Follow-up logged.");
      setFollowupNotes((prev) => ({ ...prev, [quoteId]: "" }));
      void loadQuotes();
    } else {
      setQuoteError("Failed to log follow-up.");
    }
  };

  const scheduleLink = useMemo(() => {
    if (!lead) return null;
    const params = new URLSearchParams();
    params.set("quick_create", "1");
    params.set("lead_id", lead.lead_id);
    if (lead.name) params.set("lead_name", lead.name);
    if (lead.email) params.set("lead_email", lead.email);
    if (lead.phone) params.set("lead_phone", lead.phone);
    if (lead.address) params.set("lead_address", lead.address);
    if (lead.postal_code) params.set("lead_postal_code", lead.postal_code);
    if (lead.notes) params.set("lead_notes", lead.notes);
    return `/admin/schedule?${params.toString()}`;
  }, [lead]);

  const structuredInputs = lead?.structured_inputs ?? {};
  const estimateSnapshot = lead?.estimate_snapshot ?? {};
  const estimateTotal = lead ? pickEstimateTotal(estimateSnapshot) : null;
  const estimateCurrency = "CAD";

  return (
    <div className="page">
      <AdminNav links={navLinks} activeKey="leads" />
      <section className="admin-card admin-section">
        <div className="section-heading">
          <h1>Lead Detail</h1>
          <p className="muted">Review contact details, requested service, and follow-up activity.</p>
        </div>
        {loading ? <p className="muted">Loading lead...</p> : null}
        {error ? <p className="alert alert-error">{error}</p> : null}
      </section>

      {lead ? (
        <>
          <section className="admin-card admin-section">
            <div className="section-heading" style={{ display: "flex", justifyContent: "space-between" }}>
              <div>
                <h2>{lead.name}</h2>
                <p className="muted">Lead ID: {lead.lead_id}</p>
              </div>
              {scheduleVisible && scheduleLink ? (
                <a className="btn btn-primary" href={scheduleLink}>
                  Schedule Booking
                </a>
              ) : null}
            </div>
            <div className="admin-actions" style={{ flexWrap: "wrap" }}>
              <div>
                <span className="label">Status</span>
                <div>{lead.status}</div>
              </div>
              <div>
                <span className="label">Created</span>
                <div>{formatDate(lead.created_at)}</div>
              </div>
              <div>
                <span className="label">Updated</span>
                <div>{formatDate(lead.updated_at)}</div>
              </div>
              <div>
                <span className="label">Referral credits</span>
                <div>{lead.referral_credits}</div>
              </div>
            </div>
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Contact</h2>
              <p className="muted">Primary details and contact preferences.</p>
            </div>
            <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
              <div>
                <span className="label">Email</span>
                <div>{lead.email ?? "—"}</div>
              </div>
              <div>
                <span className="label">Phone</span>
                <div>{lead.phone}</div>
              </div>
              <div>
                <span className="label">Address</span>
                <div>{lead.address ?? "—"}</div>
                <div className="muted">{lead.postal_code ?? ""}</div>
              </div>
              <div>
                <span className="label">Preferred dates</span>
                <div>{lead.preferred_dates.length ? lead.preferred_dates.join(", ") : "—"}</div>
              </div>
              <div>
                <span className="label">Access notes</span>
                <div>{lead.access_notes ?? "—"}</div>
              </div>
              <div>
                <span className="label">Parking</span>
                <div>{lead.parking ?? "—"}</div>
              </div>
              <div>
                <span className="label">Pets</span>
                <div>{lead.pets ?? "—"}</div>
              </div>
              <div>
                <span className="label">Allergies</span>
                <div>{lead.allergies ?? "—"}</div>
              </div>
            </div>
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Requested Service</h2>
              <p className="muted">Estimate snapshot captured at submission.</p>
            </div>
            <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
              <div>
                <span className="label">Beds</span>
                <div>{String(structuredInputs.beds ?? "—")}</div>
              </div>
              <div>
                <span className="label">Baths</span>
                <div>{String(structuredInputs.baths ?? "—")}</div>
              </div>
              <div>
                <span className="label">Cleaning type</span>
                <div>{String(structuredInputs.cleaning_type ?? "—")}</div>
              </div>
              <div>
                <span className="label">Frequency</span>
                <div>{String(structuredInputs.frequency ?? "—")}</div>
              </div>
              <div>
                <span className="label">Add-ons</span>
                <div>{stringifyAddOns(structuredInputs.add_ons)}</div>
              </div>
              <div>
                <span className="label">Estimate total</span>
                <div>{estimateTotal !== null ? formatCurrency(estimateTotal, estimateCurrency) : "—"}</div>
              </div>
              <div>
                <span className="label">Pricing config</span>
                <div>{lead.pricing_config_version}</div>
              </div>
            </div>
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Notes</h2>
              <p className="muted">Current notes and follow-up context.</p>
            </div>
            <div className="inline-alert">{lead.notes ?? "No notes yet."}</div>
            {lead.status === "LOST" ? (
              <div style={{ marginTop: 12 }}>
                <span className="label">Loss reason</span>
                <div>{lead.loss_reason ?? "—"}</div>
              </div>
            ) : null}
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Attribution</h2>
              <p className="muted">Source, campaign, and landing page details.</p>
            </div>
            <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
              <div>
                <span className="label">Source</span>
                <div>{lead.source ?? "—"}</div>
              </div>
              <div>
                <span className="label">Campaign</span>
                <div>{lead.campaign ?? "—"}</div>
              </div>
              <div>
                <span className="label">Keyword</span>
                <div>{lead.keyword ?? "—"}</div>
              </div>
              <div>
                <span className="label">Landing page</span>
                <div>{lead.landing_page ?? "—"}</div>
              </div>
            </div>
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Quotes</h2>
              <p className="muted">Log quotes, follow-ups, and track expiry status.</p>
            </div>
            <div className="admin-actions" style={{ flexWrap: "wrap" }}>
              <label>
                <span className="label">Amount (CAD)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={quoteAmount}
                  onChange={(event) => setQuoteAmount(event.target.value)}
                  placeholder="0.00"
                />
              </label>
              <label>
                <span className="label">Currency</span>
                <input
                  value={quoteCurrency}
                  onChange={(event) => setQuoteCurrency(event.target.value.toUpperCase())}
                  placeholder="CAD"
                />
              </label>
              <label>
                <span className="label">Service type</span>
                <input
                  value={quoteServiceType}
                  onChange={(event) => setQuoteServiceType(event.target.value)}
                  placeholder="Standard clean"
                />
              </label>
              <label>
                <span className="label">Expires</span>
                <input
                  type="date"
                  value={quoteExpiresAt}
                  onChange={(event) => setQuoteExpiresAt(event.target.value)}
                />
              </label>
              <button
                className="btn btn-secondary"
                type="button"
                disabled={!canEditLeads}
                onClick={() => void handleQuoteCreate("DRAFT")}
              >
                Create draft
              </button>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!canEditLeads}
                onClick={() => void handleQuoteCreate("SENT")}
              >
                Log sent
              </button>
            </div>
            {quoteStatus ? <p className="alert">{quoteStatus}</p> : null}
            {quoteError ? <p className="alert alert-error">{quoteError}</p> : null}
            {quotesLoading ? <p className="muted">Loading quotes...</p> : null}
            {quotesError ? <p className="alert alert-error">{quotesError}</p> : null}
            {quotes.length ? (
              <div className="table-responsive">
                <table className="table-like">
                  <thead>
                    <tr>
                      <th>Created</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Expires</th>
                      <th>Sent</th>
                      <th>Service</th>
                      <th>Follow-ups</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quotes.map((quote) => {
                      const expiresAt = quote.expires_at ? formatDate(quote.expires_at) : "—";
                      const isExpired = quote.status === "EXPIRED";
                      return (
                        <tr key={quote.quote_id}>
                          <td>{formatDate(quote.created_at)}</td>
                          <td>{formatCurrency(quote.amount / 100, quote.currency)}</td>
                          <td>{isExpired ? "EXPIRED" : quote.status}</td>
                          <td>{isExpired ? `${expiresAt} (Expired)` : expiresAt}</td>
                          <td>{quote.sent_at ? formatDateTime(quote.sent_at) : "—"}</td>
                          <td>{quote.service_type ?? "—"}</td>
                          <td>
                            {quote.followups.length ? (
                              <ul style={{ margin: 0, paddingLeft: 16 }}>
                                {quote.followups.map((followup) => (
                                  <li key={followup.followup_id}>
                                    {followup.note} · {formatDateTime(followup.created_at)}
                                    {followup.created_by ? ` · ${followup.created_by}` : ""}
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <div className="muted">No follow-ups</div>
                            )}
                            <div className="admin-actions" style={{ marginTop: 8 }}>
                              <input
                                value={followupNotes[quote.quote_id] ?? ""}
                                onChange={(event) =>
                                  setFollowupNotes((prev) => ({
                                    ...prev,
                                    [quote.quote_id]: event.target.value,
                                  }))
                                }
                                placeholder="Add follow-up note"
                              />
                              <button
                                className="btn btn-ghost"
                                type="button"
                                disabled={!canEditLeads}
                                onClick={() => void handleFollowupSubmit(quote.quote_id)}
                              >
                                Log follow-up
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No quotes logged yet.</p>
            )}
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Activity Timeline</h2>
              <p className="muted">Captured activity and status changes.</p>
            </div>
            <div className="admin-actions" style={{ flexWrap: "wrap" }}>
              <label>
                <span className="label">Activity</span>
                <select value={activity} onChange={(event) => setActivity(event.target.value)}>
                  {ACTIVITY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: 1, minWidth: 220 }}>
                <span className="label">Note</span>
                <input
                  value={activityNote}
                  onChange={(event) => setActivityNote(event.target.value)}
                  placeholder="Optional note"
                />
              </label>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!canEditLeads}
                onClick={() => void handleActivitySubmit()}
              >
                Log activity
              </button>
            </div>
            {activityStatus ? <p className="alert">{activityStatus}</p> : null}
            {activityError ? <p className="alert alert-error">{activityError}</p> : null}
            {lead.timeline.length ? (
              <div className="table-responsive">
                <table className="table-like">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Action</th>
                      <th>Actor</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lead.timeline.map((event) => (
                      <tr key={event.event_id}>
                        <td>{formatDateTime(event.timestamp)}</td>
                        <td>{event.action}</td>
                        <td>{event.actor ?? "System"}</td>
                        <td>{String(event.metadata?.note ?? "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No timeline entries yet.</p>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
