"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

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

const WEEKDAY_INDEX: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

type TrainingSessionAttendee = {
  worker_id: number;
  status: "enrolled" | "attended" | "no_show";
  worker_name?: string | null;
  block_id?: number | null;
};

type TrainingSession = {
  session_id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  location?: string | null;
  instructor_user_id?: string | null;
  notes?: string | null;
  attendees: TrainingSessionAttendee[];
};

type TrainingSessionListResponse = {
  org_timezone: string;
  from_date?: string | null;
  to_date?: string | null;
  items: TrainingSession[];
  total: number;
};

type TrainingWorkerSummary = {
  worker_id: number;
  name: string;
  team_id?: number | null;
  team_name?: string | null;
  is_active: boolean;
};

type TrainingWorkerListResponse = {
  items: TrainingWorkerSummary[];
  total: number;
};

type SessionDraft = {
  title: string;
  date: string;
  start_time: string;
  end_time: string;
  location: string;
  instructor_user_id: string;
  notes: string;
  worker_ids: number[];
};

const EMPTY_DRAFT: SessionDraft = {
  title: "",
  date: "",
  start_time: "09:00",
  end_time: "10:00",
  location: "",
  instructor_user_id: "",
  notes: "",
  worker_ids: [],
};

function formatYMDInTz(date: Date, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(date);
  const lookup: Record<string, string> = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${lookup.year}-${lookup.month}-${lookup.day}`;
}

function ymdToDate(ymd: string) {
  const [year, month, day] = ymd.split("-").map((value) => parseInt(value, 10));
  return new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
}

function monthRangeForDay(day: string, timeZone: string) {
  const base = ymdToDate(day);
  const start = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1, 12, 0, 0));
  const end = new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() + 1, 0, 12, 0, 0));
  return {
    from: formatYMDInTz(start, timeZone),
    to: formatYMDInTz(end, timeZone),
  };
}

function addDaysYMD(day: string, delta: number, timeZone: string) {
  const base = ymdToDate(day);
  base.setUTCDate(base.getUTCDate() + delta);
  return formatYMDInTz(base, timeZone);
}

function weekStartFromDay(day: string, timeZone: string) {
  const base = ymdToDate(day);
  const weekdayLabel = new Intl.DateTimeFormat("en-CA", { weekday: "short", timeZone }).format(base);
  const offset = WEEKDAY_INDEX[weekdayLabel] ?? 0;
  return addDaysYMD(day, -offset, timeZone);
}

function getTimeZoneOffsetMinutes(timeZone: string, date: Date) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const parts = formatter.formatToParts(date);
  const lookup: Record<string, string> = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const asUTC = Date.UTC(
    Number(lookup.year),
    Number(lookup.month) - 1,
    Number(lookup.day),
    Number(lookup.hour),
    Number(lookup.minute),
    Number(lookup.second)
  );
  return (asUTC - date.getTime()) / 60000;
}

function buildOrgZonedInstant(day: string, minutes: number, timeZone: string) {
  const [year, month, dayValue] = day.split("-").map((value) => parseInt(value, 10));
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  const desiredLocalAsUTC = Date.UTC(year, month - 1, dayValue, hours, mins, 0);
  const initialOffset = getTimeZoneOffsetMinutes(timeZone, new Date(desiredLocalAsUTC));
  let utcMillis = desiredLocalAsUTC - initialOffset * 60000;
  const adjustedOffset = getTimeZoneOffsetMinutes(timeZone, new Date(utcMillis));
  if (adjustedOffset !== initialOffset) {
    utcMillis = desiredLocalAsUTC - adjustedOffset * 60000;
  }
  return new Date(utcMillis);
}

function formatDateLabel(value: string, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone,
  });
  return formatter.format(ymdToDate(value)).replace(",", "");
}

function formatTimeRange(startsAt: string, endsAt: string, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  });
  return `${formatter.format(new Date(startsAt))}–${formatter.format(new Date(endsAt))}`;
}

function formatDateTimeParts(value: string, timeZone: string) {
  const date = new Date(value);
  const dateLabel = formatYMDInTz(date, timeZone);
  const timeLabel = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(date);
  return { dateLabel, timeLabel };
}

function toUtcIso(dateValue: string, timeValue: string, timeZone: string) {
  const [hour, minute] = timeValue.split(":").map((value) => parseInt(value, 10));
  const minutes = hour * 60 + minute;
  return buildOrgZonedInstant(dateValue, minutes, timeZone).toISOString();
}

export default function TrainingCalendarPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [orgTimezone, setOrgTimezone] = useState("UTC");
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [workers, setWorkers] = useState<TrainingWorkerSummary[]>([]);
  const [viewMode, setViewMode] = useState<"month" | "week">("month");
  const [selectedDate, setSelectedDate] = useState(() => formatYMDInTz(new Date(), "UTC"));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<SessionDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [activeSession, setActiveSession] = useState<TrainingSession | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const initializedDate = useRef(false);

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
    ? isVisible("module.training", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const canManage = permissionKeys.includes("training.manage");

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "leads", label: "Leads", href: "/admin/leads", featureKey: "module.leads" },
      { key: "training", label: "Training", href: "/admin/training/courses", featureKey: "module.training" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      { key: "quality", label: "Quality", href: "/admin/quality", featureKey: "module.quality" },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
  }, [featureOverrides, hiddenKeys, permissionKeys, profile, visibilityReady]);

  const range = useMemo(() => {
    if (!selectedDate) {
      const today = formatYMDInTz(new Date(), orgTimezone);
      return viewMode === "week"
        ? { from: weekStartFromDay(today, orgTimezone), to: addDaysYMD(today, 6, orgTimezone) }
        : monthRangeForDay(today, orgTimezone);
    }
    if (viewMode === "week") {
      const start = weekStartFromDay(selectedDate, orgTimezone);
      return { from: start, to: addDaysYMD(start, 6, orgTimezone) };
    }
    return monthRangeForDay(selectedDate, orgTimezone);
  }, [orgTimezone, selectedDate, viewMode]);

  const sessionsByDate = useMemo(() => {
    const mapping = new Map<string, TrainingSession[]>();
    sessions.forEach((session) => {
      const day = formatYMDInTz(new Date(session.starts_at), orgTimezone);
      if (!mapping.has(day)) mapping.set(day, []);
      mapping.get(day)?.push(session);
    });
    mapping.forEach((entries) =>
      entries.sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
    );
    return mapping;
  }, [orgTimezone, sessions]);

  const groupedDates = useMemo(() => {
    const dates: string[] = [];
    if (!range.from || !range.to) return dates;
    let cursor = range.from;
    while (cursor <= range.to) {
      dates.push(cursor);
      cursor = addDaysYMD(cursor, 1, orgTimezone);
    }
    return dates;
  }, [orgTimezone, range.from, range.to]);

  const loadProfile = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/profile`, { headers: authHeaders });
    if (response.ok) {
      const data = (await response.json()) as AdminProfile;
      setProfile(data);
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/features/config`, { headers: authHeaders });
      if (response.ok) {
        const data = (await response.json()) as FeatureConfigResponse;
        setFeatureConfig(data);
      }
    } catch (err) {
      console.error("Failed to load feature config", err);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/ui/prefs`, { headers: authHeaders });
      if (response.ok) {
        const data = (await response.json()) as UiPrefsResponse;
        setUiPrefs(data);
      }
    } catch (err) {
      console.error("Failed to load UI prefs", err);
    }
  }, [authHeaders, password, username]);

  const loadSessions = useCallback(async () => {
    if (!username || !password || !range.from || !range.to) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ from: range.from, to: range.to });
      const response = await fetch(`${API_BASE}/v1/admin/training/sessions?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Failed (${response.status})`);
      const data = (await response.json()) as TrainingSessionListResponse;
      setSessions(Array.isArray(data.items) ? data.items : []);
      if (data.org_timezone) {
        setOrgTimezone(data.org_timezone);
      }
    } catch (err) {
      console.error("Failed to load training sessions", err);
      setError("Unable to load training sessions.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, password, range.from, range.to, username]);

  const loadWorkers = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/training/workers`, { headers: authHeaders });
      if (!response.ok) throw new Error(`Failed (${response.status})`);
      const data = (await response.json()) as TrainingWorkerListResponse;
      setWorkers(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
      console.error("Failed to load workers", err);
      setWorkers([]);
    }
  }, [authHeaders, password, username]);

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
    if (!pageVisible) return;
    loadSessions();
  }, [loadSessions, pageVisible]);

  useEffect(() => {
    if (!pageVisible) return;
    loadWorkers();
  }, [loadWorkers, pageVisible]);

  useEffect(() => {
    if (initializedDate.current) return;
    if (orgTimezone === "UTC") return;
    setSelectedDate(formatYMDInTz(new Date(), orgTimezone));
    initializedDate.current = true;
  }, [orgTimezone]);

  const openCreate = useCallback(() => {
    setDraft({
      ...EMPTY_DRAFT,
      date: selectedDate || formatYMDInTz(new Date(), orgTimezone),
      worker_ids: [],
    });
    setDraftErrors([]);
    setActiveSession(null);
    setModalOpen(true);
  }, [orgTimezone, selectedDate]);

  const openEdit = useCallback(
    (sessionItem: TrainingSession) => {
      const startParts = formatDateTimeParts(sessionItem.starts_at, orgTimezone);
      const endParts = formatDateTimeParts(sessionItem.ends_at, orgTimezone);
      setDraft({
        title: sessionItem.title,
        date: startParts.dateLabel,
        start_time: startParts.timeLabel,
        end_time: endParts.timeLabel,
        location: sessionItem.location ?? "",
        instructor_user_id: sessionItem.instructor_user_id ?? "",
        notes: sessionItem.notes ?? "",
        worker_ids: sessionItem.attendees.map((attendee) => attendee.worker_id),
      });
      setDraftErrors([]);
      setActiveSession(sessionItem);
      setModalOpen(true);
    },
    [orgTimezone]
  );

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSaving(false);
    setDeleting(false);
  }, []);

  const toggleWorker = useCallback((workerId: number) => {
    setDraft((current) => {
      const set = new Set(current.worker_ids);
      if (set.has(workerId)) {
        set.delete(workerId);
      } else {
        set.add(workerId);
      }
      return { ...current, worker_ids: Array.from(set) };
    });
  }, []);

  const handleSave = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!username || !password) return;
      const errors: string[] = [];
      if (!draft.title.trim()) errors.push("Session title is required.");
      if (!draft.date) errors.push("Session date is required.");
      if (!draft.start_time || !draft.end_time) errors.push("Start and end time are required.");
      if (draft.start_time >= draft.end_time) errors.push("End time must be after start time.");
      setDraftErrors(errors);
      if (errors.length) return;

      setSaving(true);
      setStatusMessage(null);
      const payload = {
        title: draft.title.trim(),
        starts_at: toUtcIso(draft.date, draft.start_time, orgTimezone),
        ends_at: toUtcIso(draft.date, draft.end_time, orgTimezone),
        location: draft.location.trim() ? draft.location.trim() : null,
        instructor_user_id: draft.instructor_user_id.trim() ? draft.instructor_user_id.trim() : null,
        notes: draft.notes.trim() ? draft.notes.trim() : null,
      };

      try {
        if (activeSession) {
          const response = await fetch(`${API_BASE}/v1/admin/training/sessions/${activeSession.session_id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", ...authHeaders },
            body: JSON.stringify(payload),
          });
          if (!response.ok) throw new Error(`Failed (${response.status})`);
          await fetch(`${API_BASE}/v1/admin/training/sessions/${activeSession.session_id}/attendees`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders },
            body: JSON.stringify({ worker_ids: draft.worker_ids }),
          });
          setStatusMessage("Training session updated.");
        } else {
          const response = await fetch(`${API_BASE}/v1/admin/training/sessions`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders },
            body: JSON.stringify({ ...payload, worker_ids: draft.worker_ids }),
          });
          if (!response.ok) throw new Error(`Failed (${response.status})`);
          setStatusMessage("Training session created.");
        }
        await loadSessions();
        closeModal();
      } catch (err) {
        console.error("Failed to save training session", err);
        setDraftErrors(["Unable to save the training session."]);
      } finally {
        setSaving(false);
      }
    },
    [
      activeSession,
      authHeaders,
      closeModal,
      draft,
      loadSessions,
      orgTimezone,
      password,
      username,
    ]
  );

  const handleDelete = useCallback(async () => {
    if (!activeSession) return;
    setDeleting(true);
    setStatusMessage(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/training/sessions/${activeSession.session_id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (!response.ok) throw new Error(`Failed (${response.status})`);
      setStatusMessage("Training session cancelled.");
      await loadSessions();
      closeModal();
    } catch (err) {
      console.error("Failed to delete training session", err);
      setDraftErrors(["Unable to cancel the training session."]);
    } finally {
      setDeleting(false);
    }
  }, [activeSession, authHeaders, closeModal, loadSessions]);

  if (visibilityReady && !pageVisible) {
    return (
      <div className="page">
        <AdminNav links={navLinks} activeKey="training" />
        <div className="card">
          <h1>Training calendar</h1>
          <p className="muted">Training module is disabled for your account.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <AdminNav links={navLinks} activeKey="training" />
      <div className="card">
        <div className="card-row">
          <div>
            <h1>Training calendar</h1>
            <p className="muted">Schedule sessions and automatically block worker availability.</p>
          </div>
          <div className="actions">
            <a className="btn secondary" href="/admin/training/courses">
              Manage courses
            </a>
            {canManage ? (
              <button className="btn" type="button" onClick={openCreate}>
                New session
              </button>
            ) : null}
          </div>
        </div>
        <div className="card-row" style={{ flexWrap: "wrap", gap: "12px" }}>
          <div className="stack">
            <label className="muted">View</label>
            <div className="schedule-view-tabs" role="tablist">
              <button
                type="button"
                className={`schedule-view-tab${viewMode === "month" ? " active" : ""}`}
                onClick={() => setViewMode("month")}
              >
                Month
              </button>
              <button
                type="button"
                className={`schedule-view-tab${viewMode === "week" ? " active" : ""}`}
                onClick={() => setViewMode("week")}
              >
                Week
              </button>
            </div>
          </div>
          <div className="stack">
            <label className="muted">Focus date</label>
            <input
              className="input"
              type="date"
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
            />
          </div>
          <div className="stack">
            <label className="muted">Range</label>
            <div>
              {range.from} → {range.to}
            </div>
          </div>
        </div>
      </div>

      {statusMessage ? <div className="alert alert-success">{statusMessage}</div> : null}

      <div className="card">
        {error ? <div className="alert alert-error">{error}</div> : null}
        {loading ? <div className="muted">Loading sessions…</div> : null}
        {!loading && groupedDates.length === 0 ? <p className="muted">No sessions yet.</p> : null}
        <div className="stack">
          {groupedDates.map((day) => {
            const daySessions = sessionsByDate.get(day) ?? [];
            return (
              <div key={day} className="card nested">
                <div className="card-row">
                  <div>
                    <div className="title">{formatDateLabel(day, orgTimezone)}</div>
                    <div className="muted">{daySessions.length} session(s)</div>
                  </div>
                </div>
                {daySessions.length ? (
                  <div className="table">
                    <div className="table-row table-header">
                      <div>Time</div>
                      <div>Session</div>
                      <div>Attendees</div>
                      <div>Actions</div>
                    </div>
                    {daySessions.map((sessionItem) => (
                      <div className="table-row" key={sessionItem.session_id}>
                        <div>{formatTimeRange(sessionItem.starts_at, sessionItem.ends_at, orgTimezone)}</div>
                        <div>
                          <strong>{sessionItem.title}</strong>
                          <div className="muted">
                            {sessionItem.location ? sessionItem.location : "No location"}
                          </div>
                        </div>
                        <div>
                          {sessionItem.attendees.length}
                          {sessionItem.attendees.length ? (
                            <div className="muted">
                              {sessionItem.attendees
                                .map((attendee) => attendee.worker_name || `#${attendee.worker_id}`)
                                .join(", ")}
                            </div>
                          ) : null}
                        </div>
                        <div>
                          <button className="btn secondary" type="button" onClick={() => openEdit(sessionItem)}>
                            {canManage ? "Edit" : "View"}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No sessions scheduled.</p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {modalOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "720px" }}>
            <header className="schedule-modal-header">
              <div>
                <h2>{activeSession ? "Edit training session" : "Create training session"}</h2>
                <p className="muted">Times are saved in {orgTimezone}.</p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body" style={{ display: "grid", gap: "16px" }}>
              <form className="stack" onSubmit={handleSave}>
                {draftErrors.length ? (
                  <div className="error">
                    {draftErrors.map((entry) => (
                      <div key={entry}>{entry}</div>
                    ))}
                  </div>
                ) : null}
                <div className="schedule-modal-grid">
                  <div className="schedule-modal-section">
                    <label>Title</label>
                    <input
                      className="input"
                      value={draft.title}
                      onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                    />
                  </div>
                  <div className="schedule-modal-section">
                    <label>Date</label>
                    <input
                      className="input"
                      type="date"
                      value={draft.date}
                      onChange={(event) => setDraft((current) => ({ ...current, date: event.target.value }))}
                    />
                  </div>
                  <div className="schedule-modal-section">
                    <label>Start time</label>
                    <input
                      className="input"
                      type="time"
                      value={draft.start_time}
                      onChange={(event) => setDraft((current) => ({ ...current, start_time: event.target.value }))}
                    />
                  </div>
                  <div className="schedule-modal-section">
                    <label>End time</label>
                    <input
                      className="input"
                      type="time"
                      value={draft.end_time}
                      onChange={(event) => setDraft((current) => ({ ...current, end_time: event.target.value }))}
                    />
                  </div>
                  <div className="schedule-modal-section">
                    <label>Location</label>
                    <input
                      className="input"
                      value={draft.location}
                      onChange={(event) => setDraft((current) => ({ ...current, location: event.target.value }))}
                    />
                  </div>
                  <div className="schedule-modal-section">
                    <label>Instructor user ID</label>
                    <input
                      className="input"
                      value={draft.instructor_user_id}
                      onChange={(event) =>
                        setDraft((current) => ({ ...current, instructor_user_id: event.target.value }))
                      }
                    />
                  </div>
                </div>
                <div className="schedule-modal-section">
                  <label>Notes</label>
                  <textarea
                    className="input"
                    rows={3}
                    value={draft.notes}
                    onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))}
                  />
                </div>
                <div className="schedule-modal-section">
                  <label>Attendees</label>
                <div className="pill-row">
                  {workers.length ? (
                    workers.map((worker) => (
                      <label key={worker.worker_id} className="pill">
                          <input
                            type="checkbox"
                            checked={draft.worker_ids.includes(worker.worker_id)}
                            onChange={() => toggleWorker(worker.worker_id)}
                          />
                          <span>
                            {worker.name}
                            {worker.team_name ? ` · ${worker.team_name}` : ""}
                          </span>
                        </label>
                      ))
                    ) : (
                      <div className="muted">No active workers available.</div>
                    )}
                  </div>
                </div>
                <footer className="schedule-modal-footer">
                  {activeSession && canManage ? (
                    <button
                      className="btn danger"
                      type="button"
                      onClick={handleDelete}
                      disabled={deleting}
                    >
                      {deleting ? "Cancelling..." : "Cancel session"}
                    </button>
                  ) : null}
                  <div className="actions">
                    <button className="btn btn-ghost" type="button" onClick={closeModal}>
                      Close
                    </button>
                    {canManage ? (
                      <button className="btn btn-primary" type="submit" disabled={saving}>
                        {saving ? "Saving..." : "Save session"}
                      </button>
                    ) : null}
                  </div>
                </footer>
              </form>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
