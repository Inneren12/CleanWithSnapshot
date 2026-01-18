"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

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

type NurtureCampaign = {
  campaign_id: string;
  key: string;
  name: string;
  enabled: boolean;
};

type NurtureCampaignListResponse = {
  items: NurtureCampaign[];
};

type NurtureEnrollment = {
  enrollment_id: string;
  campaign_key?: string | null;
  campaign_name?: string | null;
  enrolled_at: string;
  status: string;
};

type NurtureStepLog = {
  log_id: string;
  step_index: number;
  planned_at: string;
  sent_at?: string | null;
  status: string;
  error?: string | null;
};

type NurtureEnrollmentStatus = {
  enrollment: NurtureEnrollment;
  logs: NurtureStepLog[];
};

type NurtureLeadStatusResponse = {
  items: NurtureEnrollmentStatus[];
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

type AttributionTouchpoint = {
  touchpoint_id: string;
  occurred_at: string;
  channel?: string | null;
  source?: string | null;
  campaign?: string | null;
  medium?: string | null;
  keyword?: string | null;
  landing_page?: string | null;
  metadata: Record<string, unknown>;
};

type AttributionSplitEntry = {
  touchpoint_id: string;
  label: string;
  weight: number;
  bucket: string;
};

type AttributionResponse = {
  lead_id: string;
  path: string;
  touchpoints: AttributionTouchpoint[];
  split: AttributionSplitEntry[];
  policy: {
    first_weight: number;
    middle_weight: number;
    last_weight: number;
  };
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

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
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

function formatScore(score: number) {
  return score > 0 ? `+${score}` : `${score}`;
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
  const [nurtureCampaigns, setNurtureCampaigns] = useState<NurtureCampaign[]>([]);
  const [nurtureStatus, setNurtureStatus] = useState<NurtureEnrollmentStatus[]>([]);
  const [nurtureLoading, setNurtureLoading] = useState(false);
  const [nurtureError, setNurtureError] = useState<string | null>(null);
  const [selectedCampaignKey, setSelectedCampaignKey] = useState("");
  const [enrollStatus, setEnrollStatus] = useState<string | null>(null);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [scoreSnapshot, setScoreSnapshot] = useState<ScoreSnapshot | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [scoreError, setScoreError] = useState<string | null>(null);
  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [attributionLoading, setAttributionLoading] = useState(false);
  const [attributionError, setAttributionError] = useState<string | null>(null);
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
  const nurtureVisible = visibilityReady
    ? isVisible("leads.nurture", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const nurtureEnabled = featureConfig
    ? effectiveFeatureEnabled(featureOverrides, "module.leads") &&
      effectiveFeatureEnabled(featureOverrides, "leads.nurture")
    : true;
  const scoringVisible = visibilityReady
    ? isVisible("leads.scoring", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const scoringEnabled = featureConfig
    ? effectiveFeatureEnabled(featureOverrides, "module.leads") &&
      effectiveFeatureEnabled(featureOverrides, "leads.scoring")
    : true;
  const attributionVisible = visibilityReady
    ? isVisible("analytics.attribution_multitouch", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const attributionEnabled = featureConfig
    ? effectiveFeatureEnabled(featureOverrides, "analytics.attribution_multitouch")
    : false;

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

  const loadNurtureCampaigns = useCallback(async () => {
    if (!username || !password) return;
    setNurtureLoading(true);
    setNurtureError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/nurture/campaigns`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as NurtureCampaignListResponse;
      setNurtureCampaigns(data.items ?? []);
    } else if (response.status === 403) {
      setNurtureError("You do not have permission to view nurture campaigns.");
      setNurtureCampaigns([]);
    } else {
      setNurtureError("Failed to load nurture campaigns.");
      setNurtureCampaigns([]);
    }
    setNurtureLoading(false);
  }, [authHeaders, password, username]);

  const loadNurtureStatus = useCallback(async () => {
    if (!username || !password) return;
    setNurtureLoading(true);
    setNurtureError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/nurture/status`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as NurtureLeadStatusResponse;
      setNurtureStatus(data.items ?? []);
    } else if (response.status === 403) {
      setNurtureError("You do not have permission to view nurture status.");
      setNurtureStatus([]);
    } else {
      setNurtureError("Failed to load nurture status.");
      setNurtureStatus([]);
    }
    setNurtureLoading(false);
  }, [authHeaders, leadId, password, username]);

  const loadScoreSnapshot = useCallback(async () => {
    if (!username || !password) return;
    if (!scoringEnabled) return;
    setScoreLoading(true);
    setScoreError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/scoring`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ScoreSnapshot;
      setScoreSnapshot(data);
    } else if (response.status === 404) {
      setScoreSnapshot(null);
    } else if (response.status === 403) {
      setScoreError("You do not have permission to view lead scores.");
      setScoreSnapshot(null);
    } else {
      setScoreError("Failed to load lead score.");
      setScoreSnapshot(null);
    }
    setScoreLoading(false);
  }, [authHeaders, leadId, password, scoringEnabled, username]);

  const loadAttribution = useCallback(async () => {
    if (!username || !password) return;
    if (!attributionEnabled || !attributionVisible) return;
    setAttributionLoading(true);
    setAttributionError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/attribution`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as AttributionResponse;
      setAttribution(data);
    } else if (response.status === 404) {
      setAttribution(null);
    } else if (response.status === 403) {
      setAttributionError("You do not have permission to view attribution.");
      setAttribution(null);
    } else {
      setAttributionError("Failed to load attribution.");
      setAttribution(null);
    }
    setAttributionLoading(false);
  }, [attributionEnabled, attributionVisible, authHeaders, leadId, password, username]);

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

  useEffect(() => {
    if (!nurtureEnabled) return;
    void loadNurtureCampaigns();
    void loadNurtureStatus();
  }, [loadNurtureCampaigns, loadNurtureStatus, nurtureEnabled]);

  useEffect(() => {
    void loadScoreSnapshot();
  }, [loadScoreSnapshot]);

  useEffect(() => {
    void loadAttribution();
  }, [loadAttribution]);

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

  const handleEnroll = async () => {
    if (!canEditLeads) {
      setEnrollError("Read-only role cannot enroll leads.");
      return;
    }
    if (!selectedCampaignKey.trim()) {
      setEnrollError("Select a campaign to enroll.");
      return;
    }
    setEnrollStatus(null);
    setEnrollError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}/nurture/enroll`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ campaign_key: selectedCampaignKey.trim() }),
    });
    if (response.ok) {
      setEnrollStatus("Enrollment created.");
      setSelectedCampaignKey("");
      void loadNurtureStatus();
    } else {
      setEnrollError("Failed to enroll lead.");
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
  const topScoreReasons = scoreSnapshot?.reasons.slice(0, 3) ?? [];
  const attributionTouchpoints = attribution?.touchpoints ?? [];
  const attributionSplits = attribution?.split ?? [];

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
              <h2>Lead score</h2>
              <p className="muted">Deterministic score and top drivers for this lead.</p>
            </div>
            {!scoringVisible ? <p className="alert alert-warning">Lead scoring is hidden for your profile.</p> : null}
            {!scoringEnabled ? (
              <p className="alert alert-warning">Coming soon / disabled. Enable lead scoring in Modules &amp; Visibility.</p>
            ) : null}
            {scoreLoading ? <p className="muted">Loading lead score...</p> : null}
            {scoreError ? <p className="alert alert-error">{scoreError}</p> : null}
            {scoringEnabled ? (
              <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                <div>
                  <span className="label">Score</span>
                  <div className="status-badge ok" style={{ display: "inline-flex", marginTop: "6px" }}>
                    {scoreSnapshot ? formatScore(scoreSnapshot.score) : "—"}
                  </div>
                </div>
                <div>
                  <span className="label">Rules version</span>
                  <div>{scoreSnapshot ? `v${scoreSnapshot.rules_version}` : "—"}</div>
                </div>
                <div>
                  <span className="label">Computed</span>
                  <div>{scoreSnapshot ? formatDateTime(scoreSnapshot.computed_at) : "—"}</div>
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <span className="label">Top reasons</span>
                  {topScoreReasons.length === 0 ? (
                    <p className="muted">No score recorded yet.</p>
                  ) : (
                    <ul className="clean-list" style={{ marginTop: "8px" }}>
                      {topScoreReasons.map((reason) => (
                        <li key={`${reason.rule_key}-${reason.label}`}>
                          <strong>{formatScore(reason.points)}</strong> {reason.label}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ) : null}
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <h2>Attribution path</h2>
              <p className="muted">Touchpoints captured for this lead and the deterministic split.</p>
            </div>
            {!attributionVisible ? (
              <p className="alert alert-warning">Attribution is hidden for your profile.</p>
            ) : null}
            {!attributionEnabled ? (
              <p className="alert alert-warning">
                Multi-touch attribution is disabled. Enable analytics attribution in Modules &amp; Visibility.
              </p>
            ) : null}
            {attributionLoading ? <p className="muted">Loading attribution...</p> : null}
            {attributionError ? <p className="alert alert-error">{attributionError}</p> : null}
            {attributionEnabled ? (
              <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
                <div style={{ gridColumn: "1 / -1" }}>
                  <span className="label">Path</span>
                  <div>{attribution?.path || "—"}</div>
                </div>
                <div>
                  <span className="label">Split policy</span>
                  <div>
                    {attribution
                      ? `${formatPercent(attribution.policy.first_weight)} / ${formatPercent(
                          attribution.policy.middle_weight
                        )} / ${formatPercent(attribution.policy.last_weight)}`
                      : "—"}
                  </div>
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <span className="label">Touchpoints</span>
                  {attributionTouchpoints.length === 0 ? (
                    <p className="muted">No touchpoints recorded yet.</p>
                  ) : (
                    <ul className="clean-list" style={{ marginTop: "8px" }}>
                      {attributionTouchpoints.map((touchpoint) => (
                        <li key={touchpoint.touchpoint_id}>
                          <strong>{touchpoint.channel ?? touchpoint.source ?? "Unknown"}</strong>{" "}
                          <span className="muted">{formatDateTime(touchpoint.occurred_at)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <span className="label">Split</span>
                  {attributionSplits.length === 0 ? (
                    <p className="muted">Split will appear once touchpoints are logged.</p>
                  ) : (
                    <ul className="clean-list" style={{ marginTop: "8px" }}>
                      {attributionSplits.map((entry) => (
                        <li key={`${entry.touchpoint_id}-${entry.bucket}`}>
                          <strong>{formatPercent(entry.weight)}</strong> {entry.label} ({entry.bucket})
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ) : null}
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
              <div>
                <h2>Lead nurture</h2>
                <p className="muted">Enroll this lead and review scheduled steps.</p>
              </div>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  void loadNurtureCampaigns();
                  void loadNurtureStatus();
                }}
              >
                Refresh
              </button>
            </div>
            {visibilityReady && !nurtureVisible ? (
              <p className="alert alert-warning">Lead nurture is hidden for your profile.</p>
            ) : null}
            {featureConfig && !nurtureEnabled ? (
              <p className="alert alert-warning">Lead nurture is disabled by feature flag.</p>
            ) : null}
            <div className="admin-actions" style={{ flexWrap: "wrap" }}>
              <label style={{ flex: 1, minWidth: 240 }}>
                <span className="label">Campaign</span>
                <select
                  value={selectedCampaignKey}
                  onChange={(event) => setSelectedCampaignKey(event.target.value)}
                  disabled={!nurtureEnabled}
                >
                  <option value="">Select campaign</option>
                  {nurtureCampaigns.map((campaign) => (
                    <option
                      key={campaign.campaign_id}
                      value={campaign.key}
                      disabled={!campaign.enabled}
                    >
                      {campaign.name} ({campaign.key}){campaign.enabled ? "" : " · disabled"}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="btn btn-primary"
                type="button"
                disabled={!nurtureEnabled}
                onClick={() => void handleEnroll()}
              >
                Enroll in campaign
              </button>
            </div>
            {enrollStatus ? <p className="alert">{enrollStatus}</p> : null}
            {enrollError ? <p className="alert alert-error">{enrollError}</p> : null}
            {nurtureLoading ? <p className="muted">Loading nurture data...</p> : null}
            {nurtureError ? <p className="alert alert-error">{nurtureError}</p> : null}
            {nurtureStatus.length ? (
              <div className="table-responsive">
                <table className="table-like">
                  <thead>
                    <tr>
                      <th>Campaign</th>
                      <th>Enrolled</th>
                      <th>Enrollment</th>
                      <th>Step</th>
                      <th>Planned</th>
                      <th>Sent</th>
                      <th>Status</th>
                      <th>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nurtureStatus.flatMap((entry) => {
                      const logs = entry.logs.length ? entry.logs : [null];
                      return logs.map((log) => (
                        <tr key={`${entry.enrollment.enrollment_id}-${log?.log_id ?? "none"}`}>
                          <td>{entry.enrollment.campaign_name ?? entry.enrollment.campaign_key ?? "—"}</td>
                          <td>{formatDateTime(entry.enrollment.enrolled_at)}</td>
                          <td>{entry.enrollment.status}</td>
                          <td>{log ? log.step_index : "—"}</td>
                          <td>{log ? formatDateTime(log.planned_at) : "—"}</td>
                          <td>{log?.sent_at ? formatDateTime(log.sent_at) : "—"}</td>
                          <td>{log ? log.status : "—"}</td>
                          <td>{log?.error ?? "—"}</td>
                        </tr>
                      ));
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No nurture enrollments yet.</p>
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
