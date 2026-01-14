"use client";

import { type UIEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const EDMONTON_TZ = "America/Edmonton";
const START_HOUR = 8;
const END_HOUR = 20;
const MINUTE_WIDTH = 2;
const POLL_INTERVAL_MS = 15000;

type DispatcherWorker = {
  worker_id: number;
  display_name: string;
};

type DispatcherClient = {
  id: string | null;
  name: string | null;
  phone: string | null;
};

type DispatcherAddress = {
  id: number | null;
  formatted: string | null;
  zone: string | null;
};

type DispatcherWorkerRef = {
  id: number | null;
  display_name: string | null;
  phone: string | null;
};

type DispatcherBooking = {
  booking_id: string;
  status: string;
  starts_at: string;
  ends_at: string;
  duration_min: number;
  client: DispatcherClient;
  address: DispatcherAddress;
  assigned_worker: DispatcherWorkerRef | null;
  updated_at: string;
};

type DispatcherBoardResponse = {
  bookings: DispatcherBooking[];
  workers: DispatcherWorker[];
  server_time: string;
  data_version: number;
};

type DispatcherAlert = {
  type: "DOUBLE_BOOKING" | "LATE_WORKER" | "CLIENT_CANCELLED_TODAY" | "WORKER_SHORTAGE";
  severity: "info" | "warn" | "critical";
  message: string;
  action: string;
  booking_ids: string[];
  worker_ids: number[];
};

type DispatcherAlertsResponse = {
  alerts: DispatcherAlert[];
};

const HOURS = Array.from({ length: END_HOUR - START_HOUR + 1 }, (_, index) => START_HOUR + index);
const RANGE_START_MINUTES = START_HOUR * 60;
const RANGE_END_MINUTES = END_HOUR * 60;

function formatTimeLabel(hour: number) {
  const value = hour.toString().padStart(2, "0");
  return `${value}:00`;
}

function formatTimeRange(startsAt: string, endsAt: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: EDMONTON_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${formatter.format(new Date(startsAt))}–${formatter.format(new Date(endsAt))}`;
}

function minutesFromRangeStart(value: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: EDMONTON_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(value));
  const lookup: Record<string, string> = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const hour = Number(lookup.hour ?? 0);
  const minute = Number(lookup.minute ?? 0);
  return hour * 60 + minute - RANGE_START_MINUTES;
}

function clampRange(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function bookingStatusClass(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "planned") return "planned";
  if (normalized === "in_progress") return "in-progress";
  if (normalized === "done_today") return "done-today";
  return "default";
}

function formatLastUpdated(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: EDMONTON_TZ,
  }).format(new Date(value));
}

function isoDateInTz(now: Date, tz: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const year = parts.find((part) => part.type === "year")?.value ?? "1970";
  const month = parts.find((part) => part.type === "month")?.value ?? "01";
  const day = parts.find((part) => part.type === "day")?.value ?? "01";
  return `${year}-${month}-${day}`;
}

export default function DispatcherPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [board, setBoard] = useState<DispatcherBoardResponse | null>(null);
  const [alerts, setAlerts] = useState<DispatcherAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedBooking, setSelectedBooking] = useState<DispatcherBooking | null>(null);
  const [highlightedBookingId, setHighlightedBookingId] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const hoursScrollRef = useRef<HTMLDivElement | null>(null);
  const bookingRefs = useRef<Map<string, HTMLButtonElement | null>>(new Map());

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const fetchBoard = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const isoDate = isoDateInTz(new Date(), EDMONTON_TZ);
      const response = await fetch(
        `${API_BASE}/v1/admin/dispatcher/board?date=${encodeURIComponent(
          isoDate
        )}&tz=${encodeURIComponent(EDMONTON_TZ)}`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      const payload = (await response.json()) as DispatcherBoardResponse;
      setBoard(payload);
      setLastUpdated(payload.server_time);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Unable to load dispatcher board");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, password, username]);

  const fetchAlerts = useCallback(async () => {
    if (!username || !password) return;
    try {
      const isoDate = isoDateInTz(new Date(), EDMONTON_TZ);
      const response = await fetch(
        `${API_BASE}/v1/admin/dispatcher/alerts?date=${encodeURIComponent(
          isoDate
        )}&tz=${encodeURIComponent(EDMONTON_TZ)}`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      const payload = (await response.json()) as DispatcherAlertsResponse;
      setAlerts(payload.alerts);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Unable to load dispatcher alerts");
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    void fetchBoard();
    void fetchAlerts();
    const interval = window.setInterval(() => {
      void fetchBoard();
      void fetchAlerts();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [fetchAlerts, fetchBoard, password, username]);

  const handleSaveCredentials = useCallback(() => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void fetchBoard();
  }, [fetchBoard, password, username]);

  const handleClearCredentials = useCallback(() => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setBoard(null);
    setSelectedBooking(null);
  }, []);

  const workerBookings = useMemo(() => {
    if (!board) return new Map<number, DispatcherBooking[]>();
    const mapping = new Map<number, DispatcherBooking[]>();
    board.workers.forEach((worker) => {
      mapping.set(worker.worker_id, []);
    });
    board.bookings.forEach((booking) => {
      const workerId = booking.assigned_worker?.id;
      if (!workerId) return;
      const list = mapping.get(workerId) ?? [];
      list.push(booking);
      mapping.set(workerId, list);
    });
    mapping.forEach((list) => list.sort((a, b) => a.starts_at.localeCompare(b.starts_at)));
    return mapping;
  }, [board]);

  const alertCounts = useMemo(() => {
    const counts = { info: 0, warn: 0, critical: 0 };
    alerts.forEach((alert) => {
      counts[alert.severity] += 1;
    });
    return counts;
  }, [alerts]);

  const alertsBySeverity = useMemo(() => {
    return {
      critical: alerts.filter((alert) => alert.severity === "critical"),
      warn: alerts.filter((alert) => alert.severity === "warn"),
      info: alerts.filter((alert) => alert.severity === "info"),
    };
  }, [alerts]);

  const focusAlertBooking = useCallback(
    (alert: DispatcherAlert) => {
      if (!board) return;
      const bookingId = alert.booking_ids[0];
      if (!bookingId) return;
      const booking = board.bookings.find((item) => item.booking_id === bookingId) ?? null;
      if (!booking) return;
      setSelectedBooking(booking);
      setHighlightedBookingId(bookingId);
      window.setTimeout(() => setHighlightedBookingId((current) => (current === bookingId ? null : current)), 1800);
      const target = bookingRefs.current.get(bookingId);
      target?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    },
    [board]
  );

  const totalTimelineWidth = (RANGE_END_MINUTES - RANGE_START_MINUTES) * MINUTE_WIDTH;
  const handleRowsScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    if (hoursScrollRef.current) {
      hoursScrollRef.current.scrollLeft = event.currentTarget.scrollLeft;
    }
  }, []);

  return (
    <div className="dispatcher-page">
      <header className="dispatcher-header">
        <div>
          <h1>Dispatcher Timeline</h1>
          <p className="muted">Live schedule for today in {EDMONTON_TZ}.</p>
        </div>
        <div className="dispatcher-alert-counts" aria-label="Alert counts">
          <span className="muted">Alerts</span>
          <div className="dispatcher-badges">
            <span className="dispatcher-badge critical">{alertCounts.critical}</span>
            <span className="dispatcher-badge warn">{alertCounts.warn}</span>
            <span className="dispatcher-badge info">{alertCounts.info}</span>
          </div>
        </div>
        <div className="dispatcher-updated" role="status" aria-live="polite">
          <span>Last updated</span>
          <strong>{formatLastUpdated(lastUpdated)}</strong>
        </div>
      </header>

      <section className="dispatcher-auth">
        <div className="dispatcher-auth-fields">
          <label className="field">
            <span>Username</span>
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="dispatcher"
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••"
            />
          </label>
        </div>
        <div className="dispatcher-auth-actions">
          <button className="btn btn-primary" type="button" onClick={handleSaveCredentials}>
            Save credentials
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear
          </button>
        </div>
      </section>

      <section className="dispatcher-content">
        {error ? <div className="inline-alert error">{error}</div> : null}
        {loading ? (
          <div className="dispatcher-skeleton" aria-label="Loading dispatcher board">
            <div className="skeleton-line" />
            <div className="skeleton-grid" />
          </div>
        ) : null}

        {!loading && board && board.workers.length === 0 ? (
          <div className="empty-state">No workers</div>
        ) : null}

        {!loading && board && board.workers.length > 0 && board.bookings.length === 0 ? (
          <div className="empty-state">No bookings today</div>
        ) : null}

        {!loading && board ? (
          <div className="dispatcher-grid">
            <aside className="dispatcher-alerts" aria-label="Dispatcher alerts">
              <header>
                <h2>Alerts</h2>
                <span className="muted">{alerts.length} total</span>
              </header>
              {alerts.length === 0 ? <p className="muted">No alerts for today.</p> : null}
              {alertsBySeverity.critical.length > 0 ? (
                <div className="dispatcher-alert-group">
                  <h3>Critical</h3>
                  <div className="dispatcher-alert-list">
                    {alertsBySeverity.critical.map((alert, index) => (
                      <button
                        key={`${alert.type}-${index}`}
                        type="button"
                        className="dispatcher-alert-card critical"
                        onClick={() => focusAlertBooking(alert)}
                      >
                        <strong>{alert.message}</strong>
                        <span className="muted">Action: {alert.action.split("_").join(" ")}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {alertsBySeverity.warn.length > 0 ? (
                <div className="dispatcher-alert-group">
                  <h3>Warning</h3>
                  <div className="dispatcher-alert-list">
                    {alertsBySeverity.warn.map((alert, index) => (
                      <button
                        key={`${alert.type}-${index}`}
                        type="button"
                        className="dispatcher-alert-card warn"
                        onClick={() => focusAlertBooking(alert)}
                      >
                        <strong>{alert.message}</strong>
                        <span className="muted">Action: {alert.action.split("_").join(" ")}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {alertsBySeverity.info.length > 0 ? (
                <div className="dispatcher-alert-group">
                  <h3>Info</h3>
                  <div className="dispatcher-alert-list">
                    {alertsBySeverity.info.map((alert, index) => (
                      <button
                        key={`${alert.type}-${index}`}
                        type="button"
                        className="dispatcher-alert-card info"
                        onClick={() => focusAlertBooking(alert)}
                      >
                        <strong>{alert.message}</strong>
                        <span className="muted">Action: {alert.action.split("_").join(" ")}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </aside>
            {board.workers.length > 0 ? (
              <div className="dispatcher-timeline" role="region" aria-label="Dispatcher timeline">
              <div className="dispatcher-timeline-header">
                <div className="dispatcher-worker-spacer">Worker</div>
                <div className="dispatcher-hours-scroll" ref={hoursScrollRef}>
                  <div className="dispatcher-hours" style={{ minWidth: totalTimelineWidth }}>
                    {HOURS.map((hour) => (
                      <div key={hour} className="dispatcher-hour">
                        {formatTimeLabel(hour)}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="dispatcher-timeline-body">
                <div className="dispatcher-body-scroll" onScroll={handleRowsScroll}>
                  <div className="dispatcher-worker-list">
                    {board.workers.map((worker) => (
                      <div key={worker.worker_id} className="dispatcher-worker-name">
                        {worker.display_name || `Worker ${worker.worker_id}`}
                      </div>
                    ))}
                  </div>
                  <div className="dispatcher-rows">
                    {board.workers.map((worker) => (
                      <div key={worker.worker_id} className="dispatcher-row">
                        <div
                          className="dispatcher-row-track"
                          style={{ minWidth: totalTimelineWidth }}
                          aria-label={`Timeline for ${worker.display_name}`}
                        >
                          {(workerBookings.get(worker.worker_id) ?? []).map((booking) => {
                            const startOffset = clampRange(
                              minutesFromRangeStart(booking.starts_at),
                              0,
                              RANGE_END_MINUTES
                            );
                            const endOffset = clampRange(
                              minutesFromRangeStart(booking.ends_at),
                              0,
                              RANGE_END_MINUTES
                            );
                            const width = Math.max((endOffset - startOffset) * MINUTE_WIDTH, 24);
                            const isHighlighted = highlightedBookingId === booking.booking_id;
                            return (
                              <button
                                key={booking.booking_id}
                                type="button"
                                ref={(element) => {
                                  bookingRefs.current.set(booking.booking_id, element);
                                }}
                                className={`dispatcher-booking ${bookingStatusClass(booking.status)}${
                                  isHighlighted ? " alert-focus" : ""
                                }`}
                                style={{
                                  left: `${startOffset * MINUTE_WIDTH}px`,
                                  width: `${width}px`,
                                }}
                                onClick={() => setSelectedBooking(booking)}
                                aria-label={`Booking for ${booking.client?.name ?? "client"}`}
                              >
                                <div className="dispatcher-booking-title">
                                  {booking.client?.name ?? "Unnamed client"}
                                </div>
                                <div className="dispatcher-booking-subtitle">
                                  {formatTimeRange(booking.starts_at, booking.ends_at)}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {selectedBooking ? (
        <div className="dispatcher-drawer" role="dialog" aria-modal="true">
          <div className="dispatcher-drawer-backdrop" onClick={() => setSelectedBooking(null)} />
          <aside className="dispatcher-drawer-panel">
            <header>
              <h2>Booking details</h2>
              <button className="btn btn-ghost" onClick={() => setSelectedBooking(null)} type="button">
                Close
              </button>
            </header>
            <div className="dispatcher-drawer-content">
              <div className="detail">
                <span className="detail-label">Client</span>
                <strong>{selectedBooking.client?.name ?? "—"}</strong>
              </div>
              <div className="detail">
                <span className="detail-label">Address</span>
                <strong>{selectedBooking.address?.formatted ?? "—"}</strong>
              </div>
              <div className="detail">
                <span className="detail-label">Time</span>
                <strong>{formatTimeRange(selectedBooking.starts_at, selectedBooking.ends_at)}</strong>
              </div>
              <div className="detail">
                <span className="detail-label">Status</span>
                <strong>{selectedBooking.status}</strong>
              </div>
              <div className="detail">
                <span className="detail-label">Worker</span>
                <strong>{selectedBooking.assigned_worker?.display_name ?? "Unassigned"}</strong>
              </div>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
