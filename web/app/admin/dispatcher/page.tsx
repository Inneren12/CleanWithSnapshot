"use client";

import Script from "next/script";
import { type DragEvent, type UIEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const EDMONTON_TZ = "America/Edmonton";
const EDMONTON_CENTER = { lat: 53.5461, lng: -113.4938 };
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
  lat?: number | null;
  lng?: number | null;
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

type DispatcherStatsResponse = {
  done_count: number;
  in_progress_count: number;
  planned_count: number;
  avg_duration_hours: number | null;
  revenue_today: number;
};

type DispatcherNotifyResponse = {
  audit_id: string;
  status: "sent" | "failed";
  error_code: string | null;
  provider_msg_id: string | null;
  sent_at: string;
};

type DispatcherNotifyAuditEntry = {
  audit_id: string;
  booking_id: string;
  target: "client" | "worker";
  channel: "sms" | "call";
  template_id: string;
  admin_user_id: string;
  status: "sent" | "failed";
  error_code: string | null;
  provider_msg_id: string | null;
  sent_at: string;
};

type DispatcherNotifyAuditResponse = {
  audits: DispatcherNotifyAuditEntry[];
};

type RouteEstimateResponse = {
  distance_km: number;
  duration_min: number;
  duration_in_traffic_min: number | null;
  provider: "google" | "heuristic";
  cached: boolean;
};

type DispatcherSuggestionScoreParts = {
  availability: number;
  distance: number;
  skill: number;
  rating: number;
  workload: number;
};

type DispatcherAssignmentSuggestion = {
  worker_id: number;
  display_name: string | null;
  score_total: number;
  score_parts: DispatcherSuggestionScoreParts;
  eta_min: number | null;
  reasons: string[];
};

type DispatcherAssignmentSuggestionsResponse = {
  suggestions: DispatcherAssignmentSuggestion[];
};

const HOURS = Array.from({ length: END_HOUR - START_HOUR + 1 }, (_, index) => START_HOUR + index);
const RANGE_START_MINUTES = START_HOUR * 60;
const RANGE_END_MINUTES = END_HOUR * 60;
const ZONE_OPTIONS = [
  "All",
  "Downtown",
  "Whyte/Old Strathcona",
  "West",
  "South/Millwoods",
  "North/Castle Downs",
  "St. Albert",
];
const DISPATCHER_TEMPLATES = [
  { id: "WORKER_EN_ROUTE_15MIN", label: "Worker: route reminder (15 min)" },
  { id: "CLIENT_DELAY_TRAFFIC", label: "Client: delay due to traffic" },
  { id: "CLIENT_DONE", label: "Client: cleaning complete" },
];

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

function formatStartTime(startsAt: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: EDMONTON_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return formatter.format(new Date(startsAt));
}

function formatDateTimeLocal(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hour = `${date.getHours()}`.padStart(2, "0");
  const minute = `${date.getMinutes()}`.padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function parseDateTimeLocal(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function diffMinutes(start: Date, end: Date) {
  return Math.round((end.getTime() - start.getTime()) / 60000);
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
  if (normalized === "done_today" || normalized === "done") return "done-today";
  return "default";
}

function bookingStatusColor(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "planned") return "#2563eb";
  if (normalized === "in_progress") return "#16a34a";
  if (normalized === "done_today" || normalized === "done") return "#f59e0b";
  return "#64748b";
}

function formatLastUpdated(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: EDMONTON_TZ,
  }).format(new Date(value));
}

function formatAuditTime(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: EDMONTON_TZ,
  }).format(new Date(value));
}

function formatCurrencyFromCents(value: number) {
  const formatter = new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  });
  return formatter.format(value / 100);
}

function formatDurationMinutes(value: number) {
  return `${value} min`;
}

function formatDistanceKm(value: number) {
  return `${value.toFixed(1)} km`;
}

function formatDurationDelta(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${Math.abs(value)} min`;
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

function shortAddress(address: DispatcherAddress | null | undefined) {
  const formatted = address?.formatted ?? "";
  if (!formatted) return "Address unavailable";
  const [street] = formatted.split(",");
  return street?.trim() || formatted;
}

export default function DispatcherPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [board, setBoard] = useState<DispatcherBoardResponse | null>(null);
  const [stats, setStats] = useState<DispatcherStatsResponse | null>(null);
  const [alerts, setAlerts] = useState<DispatcherAlert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: "error" | "success"; message: string } | null>(null);
  const [selectedBooking, setSelectedBooking] = useState<DispatcherBooking | null>(null);
  const [highlightedBookingId, setHighlightedBookingId] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [pendingActionIds, setPendingActionIds] = useState<string[]>([]);
  const [reassignWorkerId, setReassignWorkerId] = useState<string>("");
  const [rescheduleStart, setRescheduleStart] = useState("");
  const [rescheduleEnd, setRescheduleEnd] = useState("");
  const [rescheduleOverride, setRescheduleOverride] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [commTarget, setCommTarget] = useState<"client" | "worker">("client");
  const [commChannel, setCommChannel] = useState<"sms" | "call">("sms");
  const [commTemplateId, setCommTemplateId] = useState(DISPATCHER_TEMPLATES[1]?.id ?? "");
  const [commAudits, setCommAudits] = useState<DispatcherNotifyAuditEntry[]>([]);
  const [commError, setCommError] = useState<string | null>(null);
  const [currentRouteEstimate, setCurrentRouteEstimate] = useState<RouteEstimateResponse | null>(null);
  const [currentRouteError, setCurrentRouteError] = useState<string | null>(null);
  const [currentRoutePending, setCurrentRoutePending] = useState(false);
  const [reassignRouteEstimate, setReassignRouteEstimate] = useState<RouteEstimateResponse | null>(null);
  const [reassignRouteError, setReassignRouteError] = useState<string | null>(null);
  const [reassignRoutePending, setReassignRoutePending] = useState(false);
  const [suggestions, setSuggestions] = useState<DispatcherAssignmentSuggestion[]>([]);
  const [suggestionsPending, setSuggestionsPending] = useState(false);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);
  const [draggingBookingId, setDraggingBookingId] = useState<string | null>(null);
  const [dragOverWorkerId, setDragOverWorkerId] = useState<number | null>(null);
  const [selectedZone, setSelectedZone] = useState<string>("All");
  const [viewMode, setViewMode] = useState<"timeline" | "map" | "split">("split");
  const [isSmallScreen, setIsSmallScreen] = useState(false);
  const [mapScriptsLoaded, setMapScriptsLoaded] = useState(false);
  const [clustererLoaded, setClustererLoaded] = useState(false);
  const hoursScrollRef = useRef<HTMLDivElement | null>(null);
  const bookingRefs = useRef<Map<string, HTMLButtonElement | null>>(new Map());
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<any>(null);
  const mapMarkersRef = useRef<any[]>([]);
  const mapClustererRef = useRef<any>(null);
  const mapInfoWindowRef = useRef<any>(null);
  const lastBoundsRef = useRef<any>(null);

  const mapApiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
  const hasMapKey = Boolean(mapApiKey);

  const isAuthenticated = Boolean(username && password);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const showToast = useCallback((message: string, kind: "error" | "success" = "error") => {
    setToast({ message, kind });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    if (!selectedBooking) {
      setCommAudits([]);
      setCommError(null);
      return;
    }
    setCommTarget("client");
    setCommChannel("sms");
    setCommTemplateId(DISPATCHER_TEMPLATES[1]?.id ?? "");
  }, [selectedBooking]);

  useEffect(() => {
    setSuggestions([]);
    setSuggestionsError(null);
    setSuggestionsPending(false);
  }, [selectedBooking]);

  const fetchBoard = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const isoDate = isoDateInTz(new Date(), EDMONTON_TZ);
      const zoneParam = selectedZone === "All" ? null : selectedZone;
      const zoneQuery = zoneParam ? `&zone=${encodeURIComponent(zoneParam)}` : "";
      const response = await fetch(
        `${API_BASE}/v1/admin/dispatcher/board?date=${encodeURIComponent(
          isoDate
        )}&tz=${encodeURIComponent(EDMONTON_TZ)}${zoneQuery}`,
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
  }, [authHeaders, password, selectedZone, username]);

  const fetchStats = useCallback(async () => {
    if (!username || !password) return;
    try {
      const isoDate = isoDateInTz(new Date(), EDMONTON_TZ);
      const zoneParam = selectedZone === "All" ? null : selectedZone;
      const zoneQuery = zoneParam ? `&zone=${encodeURIComponent(zoneParam)}` : "";
      const response = await fetch(
        `${API_BASE}/v1/admin/dispatcher/stats?date=${encodeURIComponent(
          isoDate
        )}&tz=${encodeURIComponent(EDMONTON_TZ)}${zoneQuery}`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      const payload = (await response.json()) as DispatcherStatsResponse;
      setStats(payload);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Unable to load dispatcher stats");
    }
  }, [authHeaders, password, selectedZone, username]);

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

  const fetchNotifyAudits = useCallback(async () => {
    if (!isAuthenticated || !selectedBooking) return;
    setCommError(null);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/dispatcher/notify/audit?booking_id=${encodeURIComponent(
          selectedBooking.booking_id
        )}&limit=5`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      const payload = (await response.json()) as DispatcherNotifyAuditResponse;
      setCommAudits(payload.audits);
    } catch (fetchError) {
      setCommError(fetchError instanceof Error ? fetchError.message : "Unable to load communication history");
    }
  }, [authHeaders, isAuthenticated, selectedBooking]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(max-width: 900px)");
    const isSmall = mediaQuery.matches;
    setIsSmallScreen(isSmall);
    setViewMode(isSmall ? "timeline" : "split");
    const handleChange = (event: MediaQueryListEvent) => setIsSmallScreen(event.matches);
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener("change", handleChange);
    } else {
      mediaQuery.addListener(handleChange);
    }
    return () => {
      if (mediaQuery.removeEventListener) {
        mediaQuery.removeEventListener("change", handleChange);
      } else {
        mediaQuery.removeListener(handleChange);
      }
    };
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    void fetchBoard();
    void fetchAlerts();
    void fetchStats();
    const interval = window.setInterval(() => {
      void fetchBoard();
      void fetchAlerts();
      void fetchStats();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [fetchAlerts, fetchBoard, fetchStats, password, username]);

  useEffect(() => {
    if (!selectedBooking) return;
    setReassignWorkerId(selectedBooking.assigned_worker?.id?.toString() ?? "");
    setRescheduleStart(formatDateTimeLocal(selectedBooking.starts_at));
    setRescheduleEnd(formatDateTimeLocal(selectedBooking.ends_at));
    setRescheduleOverride(false);
    setCancelReason("");
  }, [selectedBooking]);

  useEffect(() => {
    if (!selectedBooking) return;
    void fetchNotifyAudits();
  }, [fetchNotifyAudits, selectedBooking]);


  const handleSaveCredentials = useCallback(() => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void fetchBoard();
    void fetchStats();
  }, [fetchBoard, fetchStats, password, username]);

  const handleClearCredentials = useCallback(() => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setBoard(null);
    setStats(null);
    setSelectedBooking(null);
  }, []);

  const updateBookingState = useCallback(
    (bookingId: string, updater: (booking: DispatcherBooking) => DispatcherBooking) => {
      setBoard((current) => {
        if (!current) return current;
        const bookings = current.bookings.map((booking) =>
          booking.booking_id === bookingId ? updater(booking) : booking
        );
        return { ...current, bookings };
      });
      setSelectedBooking((current) => {
        if (!current || current.booking_id !== bookingId) return current;
        return updater(current);
      });
    },
    []
  );

  const setActionPending = useCallback((bookingId: string, pending: boolean) => {
    setPendingActionIds((current) => {
      if (pending) {
        return current.includes(bookingId) ? current : [...current, bookingId];
      }
      return current.filter((id) => id !== bookingId);
    });
  }, []);

  const applyOptimisticUpdate = useCallback(
    async (
      bookingId: string,
      optimisticUpdate: (booking: DispatcherBooking) => DispatcherBooking,
      request: () => Promise<Response>
    ) => {
      if (!board) return;
      const previous = board.bookings.find((booking) => booking.booking_id === bookingId);
      if (!previous) return;
      updateBookingState(bookingId, optimisticUpdate);
      setActionPending(bookingId, true);
      try {
        const response = await request();
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          const message =
            typeof payload?.detail === "string"
              ? payload.detail
              : typeof payload?.detail?.message === "string"
                ? payload.detail.message
                : `Request failed (${response.status})`;
          throw new Error(message);
        }
        if (payload) {
          updateBookingState(bookingId, () => payload as DispatcherBooking);
        }
      } catch (requestError) {
        updateBookingState(bookingId, () => previous);
        showToast(
          requestError instanceof Error ? requestError.message : "Unable to update booking",
          "error"
        );
      } finally {
        setActionPending(bookingId, false);
      }
    },
    [board, setActionPending, showToast, updateBookingState]
  );

  const workerBookings = useMemo<Map<number, DispatcherBooking[]>>(() => {
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

  const workerNames = useMemo(() => {
    const mapping = new Map<number, string>();
    board?.workers.forEach((worker) => {
      mapping.set(worker.worker_id, worker.display_name || `Worker ${worker.worker_id}`);
    });
    return mapping;
  }, [board]);

  const resolveWorkerOrigin = useCallback(
    (workerId: number | null | undefined, targetStartsAt: string) => {
      if (!workerId) return null;
      const list = workerBookings.get(workerId);
      if (!list || list.length === 0) return null;
      const targetStart = new Date(targetStartsAt).getTime();
      let candidate: DispatcherBooking | undefined;
      for (const booking of list) {
        const bookingStart = new Date(booking.starts_at).getTime();
        if (Number.isNaN(bookingStart) || bookingStart >= targetStart) continue;
        if (!candidate) {
          candidate = booking;
          continue;
        }
        const candidateEnd = new Date(candidate.ends_at).getTime();
        const bookingEnd = new Date(booking.ends_at).getTime();
        if (!Number.isNaN(bookingEnd) && bookingEnd >= candidateEnd) {
          candidate = booking;
        }
      }
      if (!candidate) return null;
      const lat = candidate.address?.lat;
      const lng = candidate.address?.lng;
      if (lat == null || lng == null) return null;
      return {
        lat,
        lng,
        label: shortAddress(candidate.address),
        bookingId: candidate.booking_id,
      };
    },
    [workerBookings]
  );

  const fetchRouteEstimate = useCallback(
    async (origin: { lat: number; lng: number }, dest: { lat: number; lng: number }, departAt?: string) => {
      const response = await fetch(`${API_BASE}/v1/admin/dispatcher/routes/estimate`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({
          origin,
          dest,
          depart_at: departAt ?? null,
          mode: "driving",
        }),
      });
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      return (await response.json()) as RouteEstimateResponse;
    },
    [authHeaders]
  );

  const fetchSuggestions = useCallback(async () => {
    if (!selectedBooking || !isAuthenticated) return;
    setSuggestionsPending(true);
    setSuggestionsError(null);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/dispatcher/assign/suggest?booking_id=${encodeURIComponent(
          selectedBooking.booking_id
        )}&limit=5`,
        {
          headers: authHeaders,
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        const message =
          typeof payload?.detail === "string" ? payload.detail : `Request failed (${response.status})`;
        throw new Error(message);
      }
      setSuggestions((payload as DispatcherAssignmentSuggestionsResponse).suggestions ?? []);
    } catch (requestError) {
      setSuggestions([]);
      setSuggestionsError(requestError instanceof Error ? requestError.message : "Unable to load suggestions");
    } finally {
      setSuggestionsPending(false);
    }
  }, [authHeaders, isAuthenticated, selectedBooking]);

  useEffect(() => {
    if (!selectedBooking || !isAuthenticated) {
      setCurrentRouteEstimate(null);
      setCurrentRouteError(null);
      setCurrentRoutePending(false);
      return;
    }
    const destinationLat = selectedBooking.address?.lat;
    const destinationLng = selectedBooking.address?.lng;
    const origin = resolveWorkerOrigin(selectedBooking.assigned_worker?.id ?? null, selectedBooking.starts_at);
    if (destinationLat == null || destinationLng == null) {
      setCurrentRouteEstimate(null);
      setCurrentRouteError("Missing booking location.");
      setCurrentRoutePending(false);
      return;
    }
    if (!origin) {
      setCurrentRouteEstimate(null);
      setCurrentRouteError("No previous booking location.");
      setCurrentRoutePending(false);
      return;
    }
    setCurrentRouteError(null);
    let isActive = true;
    const timeout = window.setTimeout(() => {
      setCurrentRoutePending(true);
      fetchRouteEstimate(origin, { lat: destinationLat, lng: destinationLng }, selectedBooking.starts_at)
        .then((payload) => {
          if (!isActive) return;
          setCurrentRouteEstimate(payload);
        })
        .catch((routeError) => {
          if (!isActive) return;
          setCurrentRouteError(routeError instanceof Error ? routeError.message : "Route estimate failed.");
          setCurrentRouteEstimate(null);
        })
        .finally(() => {
          if (!isActive) return;
          setCurrentRoutePending(false);
        });
    }, 400);
    return () => {
      isActive = false;
      window.clearTimeout(timeout);
    };
  }, [fetchRouteEstimate, isAuthenticated, resolveWorkerOrigin, selectedBooking]);

  useEffect(() => {
    if (!selectedBooking || !isAuthenticated) {
      setReassignRouteEstimate(null);
      setReassignRouteError(null);
      setReassignRoutePending(false);
      return;
    }
    const destinationLat = selectedBooking.address?.lat;
    const destinationLng = selectedBooking.address?.lng;
    const workerId = reassignWorkerId ? Number(reassignWorkerId) : null;
    if (!workerId || workerId === selectedBooking.assigned_worker?.id) {
      setReassignRouteEstimate(null);
      setReassignRouteError(null);
      setReassignRoutePending(false);
      return;
    }
    if (destinationLat == null || destinationLng == null) {
      setReassignRouteEstimate(null);
      setReassignRouteError("Missing booking location.");
      setReassignRoutePending(false);
      return;
    }
    const origin = resolveWorkerOrigin(workerId, selectedBooking.starts_at);
    if (!origin) {
      setReassignRouteEstimate(null);
      setReassignRouteError("No previous booking location.");
      setReassignRoutePending(false);
      return;
    }
    setReassignRouteError(null);
    let isActive = true;
    const timeout = window.setTimeout(() => {
      setReassignRoutePending(true);
      fetchRouteEstimate(origin, { lat: destinationLat, lng: destinationLng }, selectedBooking.starts_at)
        .then((payload) => {
          if (!isActive) return;
          setReassignRouteEstimate(payload);
        })
        .catch((routeError) => {
          if (!isActive) return;
          setReassignRouteError(routeError instanceof Error ? routeError.message : "Route estimate failed.");
          setReassignRouteEstimate(null);
        })
        .finally(() => {
          if (!isActive) return;
          setReassignRoutePending(false);
        });
    }, 400);
    return () => {
      isActive = false;
      window.clearTimeout(timeout);
    };
  }, [
    fetchRouteEstimate,
    isAuthenticated,
    reassignWorkerId,
    resolveWorkerOrigin,
    selectedBooking,
  ]);

  const currentOriginInfo = useMemo(() => {
    if (!selectedBooking) return null;
    return resolveWorkerOrigin(selectedBooking.assigned_worker?.id ?? null, selectedBooking.starts_at);
  }, [resolveWorkerOrigin, selectedBooking]);

  const reassignOriginInfo = useMemo(() => {
    if (!selectedBooking || !reassignWorkerId) return null;
    return resolveWorkerOrigin(Number(reassignWorkerId), selectedBooking.starts_at);
  }, [reassignWorkerId, resolveWorkerOrigin, selectedBooking]);

  const reassignWorkerName = useMemo(() => {
    if (!reassignWorkerId) return null;
    const workerId = Number(reassignWorkerId);
    return workerNames.get(workerId) ?? `Worker ${workerId}`;
  }, [reassignWorkerId, workerNames]);

  const routeDeltaMinutes = useMemo(() => {
    if (!currentRouteEstimate || !reassignRouteEstimate) return null;
    return reassignRouteEstimate.duration_min - currentRouteEstimate.duration_min;
  }, [currentRouteEstimate, reassignRouteEstimate]);

  const alertCounts = useMemo(() => {
    const counts = { info: 0, warn: 0, critical: 0 };
    alerts.forEach((alert) => {
      counts[alert.severity] += 1;
    });
    return counts;
  }, [alerts]);

  const isActionPending = useCallback(
    (bookingId: string) => pendingActionIds.includes(bookingId),
    [pendingActionIds]
  );

  const alertsBySeverity = useMemo(() => {
    return {
      critical: alerts.filter((alert) => alert.severity === "critical"),
      warn: alerts.filter((alert) => alert.severity === "warn"),
      info: alerts.filter((alert) => alert.severity === "info"),
    };
  }, [alerts]);

  const handleReassign = useCallback(
    async (bookingId: string, workerId: number) => {
      if (!isAuthenticated) {
        showToast("Save credentials to manage bookings.");
        return;
      }
      const assignedWorker = board?.workers.find((worker) => worker.worker_id === workerId);
      const workerPayload = {
        id: workerId,
        display_name: assignedWorker?.display_name ?? null,
        phone: null,
      };
      await applyOptimisticUpdate(
        bookingId,
        (booking) => ({
          ...booking,
          assigned_worker: workerPayload,
          updated_at: new Date().toISOString(),
        }),
        () =>
          fetch(`${API_BASE}/v1/admin/dispatcher/bookings/${bookingId}/reassign`, {
            method: "POST",
            headers: { ...authHeaders, "Content-Type": "application/json" },
            body: JSON.stringify({ worker_id: workerId }),
          })
      );
    },
    [applyOptimisticUpdate, authHeaders, board, isAuthenticated, showToast]
  );

  const handleReschedule = useCallback(async () => {
    if (!selectedBooking) return;
    if (!isAuthenticated) {
      showToast("Save credentials to manage bookings.");
      return;
    }
    const startDate = parseDateTimeLocal(rescheduleStart);
    const endDate = parseDateTimeLocal(rescheduleEnd);
    if (!startDate || !endDate) {
      showToast("Select valid start and end times.");
      return;
    }
    if (endDate <= startDate) {
      showToast("End time must be after start time.");
      return;
    }
    const durationMinutes = diffMinutes(startDate, endDate);
    const startIso = startDate.toISOString();
    const endIso = endDate.toISOString();
    await applyOptimisticUpdate(
      selectedBooking.booking_id,
      (booking) => ({
        ...booking,
        starts_at: startIso,
        ends_at: endIso,
        duration_min: durationMinutes,
        updated_at: new Date().toISOString(),
      }),
      () =>
        fetch(`${API_BASE}/v1/admin/dispatcher/bookings/${selectedBooking.booking_id}/reschedule`, {
          method: "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify({
            starts_at: startIso,
            ends_at: endIso,
            override_conflicts: rescheduleOverride,
          }),
        })
    );
  }, [
    applyOptimisticUpdate,
    authHeaders,
    isAuthenticated,
    rescheduleEnd,
    rescheduleOverride,
    rescheduleStart,
    selectedBooking,
    showToast,
  ]);

  const handleStatusUpdate = useCallback(
    async (statusValue: "IN_PROGRESS" | "DONE") => {
      if (!selectedBooking) return;
      if (!isAuthenticated) {
        showToast("Save credentials to manage bookings.");
        return;
      }
      await applyOptimisticUpdate(
        selectedBooking.booking_id,
        (booking) => ({
          ...booking,
          status: statusValue,
          updated_at: new Date().toISOString(),
        }),
        () =>
          fetch(`${API_BASE}/v1/admin/dispatcher/bookings/${selectedBooking.booking_id}/status`, {
            method: "POST",
            headers: { ...authHeaders, "Content-Type": "application/json" },
            body: JSON.stringify({ status: statusValue }),
          })
      );
    },
    [applyOptimisticUpdate, authHeaders, isAuthenticated, selectedBooking, showToast]
  );

  const handleCancel = useCallback(async () => {
    if (!selectedBooking) return;
    if (!isAuthenticated) {
      showToast("Save credentials to manage bookings.");
      return;
    }
    if (!cancelReason.trim()) {
      showToast("Cancellation reason is required.");
      return;
    }
    await applyOptimisticUpdate(
      selectedBooking.booking_id,
      (booking) => ({
        ...booking,
        status: "CANCELLED",
        updated_at: new Date().toISOString(),
      }),
      () =>
        fetch(`${API_BASE}/v1/admin/dispatcher/bookings/${selectedBooking.booking_id}/status`, {
          method: "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify({ status: "CANCELLED", reason: cancelReason.trim() }),
        })
    );
  }, [applyOptimisticUpdate, authHeaders, cancelReason, isAuthenticated, selectedBooking, showToast]);

  const handleNotify = useCallback(
    async (target: "client" | "worker", channel: "sms" | "call", templateId: string) => {
      if (!selectedBooking) return;
      if (!isAuthenticated) {
        showToast("Save credentials to contact clients or workers.");
        return;
      }
      if (channel === "sms") {
        const confirmed = window.confirm("Send this SMS now?");
        if (!confirmed) return;
      }
      setActionPending(selectedBooking.booking_id, true);
      try {
        const response = await fetch(`${API_BASE}/v1/admin/dispatcher/notify`, {
          method: "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify({
            booking_id: selectedBooking.booking_id,
            target,
            channel,
            template_id: templateId,
            params: {},
          }),
        });
        const payload = (await response.json()) as DispatcherNotifyResponse;
        if (!response.ok) {
          const message =
            typeof (payload as { detail?: string })?.detail === "string"
              ? (payload as { detail?: string }).detail
              : `Request failed (${response.status})`;
          throw new Error(message);
        }
        if (payload.status === "sent") {
          showToast("Message sent.", "success");
        } else {
          showToast(payload.error_code ?? "Message failed to send.");
        }
        await fetchNotifyAudits();
      } catch (notifyError) {
        showToast(
          notifyError instanceof Error ? notifyError.message : "Unable to send notification",
          "error"
        );
      } finally {
        setActionPending(selectedBooking.booking_id, false);
      }
    },
    [authHeaders, fetchNotifyAudits, isAuthenticated, selectedBooking, setActionPending, showToast]
  );

  const handleDragStart = useCallback((bookingId: string) => {
    return (event: DragEvent<HTMLButtonElement>) => {
      event.dataTransfer.setData("text/plain", bookingId);
      event.dataTransfer.effectAllowed = "move";
      setDraggingBookingId(bookingId);
    };
  }, []);

  const handleDragEnd = useCallback(() => {
    setDraggingBookingId(null);
    setDragOverWorkerId(null);
  }, []);

  const handleDropOnWorker = useCallback(
    (workerId: number) => {
      return async (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        const bookingId = event.dataTransfer.getData("text/plain");
        setDragOverWorkerId(null);
        if (!bookingId) return;
        const booking = board?.bookings.find((item) => item.booking_id === bookingId);
        if (!booking) return;
        if (booking.assigned_worker?.id === workerId) return;
        await handleReassign(bookingId, workerId);
      };
    },
    [board, handleReassign]
  );

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const handleDragEnter = useCallback((workerId: number) => {
    return () => setDragOverWorkerId(workerId);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOverWorkerId(null);
  }, []);

  const focusBooking = useCallback((booking: DispatcherBooking) => {
    setSelectedBooking(booking);
    setHighlightedBookingId(booking.booking_id);
    window.setTimeout(
      () => setHighlightedBookingId((current) => (current === booking.booking_id ? null : current)),
      1800
    );
    const target = bookingRefs.current.get(booking.booking_id);
    target?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  }, []);

  const focusAlertBooking = useCallback(
    (alert: DispatcherAlert) => {
      if (!board) return;
      const bookingId = alert.booking_ids[0];
      if (!bookingId) return;
      const booking = board.bookings.find((item) => item.booking_id === bookingId) ?? null;
      if (!booking) return;
      focusBooking(booking);
    },
    [board, focusBooking]
  );

  const handleMapBookingSelect = useCallback(
    (booking: DispatcherBooking) => {
      if (viewMode === "map") {
        setViewMode(isSmallScreen ? "timeline" : "split");
      }
      focusBooking(booking);
    },
    [focusBooking, isSmallScreen, viewMode]
  );

  const mapBookings = useMemo(() => board?.bookings ?? [], [board]);

  const mapLocations = useMemo(() => {
    const withCoords: Array<{ booking: DispatcherBooking; lat: number; lng: number }> = [];
    let missingCount = 0;
    mapBookings.forEach((booking) => {
      const lat = booking.address?.lat;
      const lng = booking.address?.lng;
      if (typeof lat === "number" && typeof lng === "number") {
        withCoords.push({ booking, lat, lng });
      } else {
        missingCount += 1;
      }
    });
    return { withCoords, missingCount };
  }, [mapBookings]);

  useEffect(() => {
    if (!mapScriptsLoaded || !hasMapKey) return;
    if (!mapContainerRef.current) return;
    if (!(window as any).google?.maps) return;
    if (!mapInstanceRef.current) {
      mapInstanceRef.current = new (window as any).google.maps.Map(mapContainerRef.current, {
        center: EDMONTON_CENTER,
        zoom: 11,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
      });
      mapInfoWindowRef.current = new (window as any).google.maps.InfoWindow();
    }
  }, [hasMapKey, mapScriptsLoaded]);

  useEffect(() => {
    if (!mapScriptsLoaded || !hasMapKey) return;
    const googleMaps = (window as any).google?.maps;
    const map = mapInstanceRef.current;
    if (!googleMaps || !map) return;

    mapMarkersRef.current.forEach((marker) => marker.setMap(null));
    mapMarkersRef.current = [];
    if (mapClustererRef.current?.clearMarkers) {
      mapClustererRef.current.clearMarkers();
      mapClustererRef.current = null;
    }

    if (mapLocations.withCoords.length === 0) {
      map.setCenter(EDMONTON_CENTER);
      map.setZoom(11);
      lastBoundsRef.current = null;
      return;
    }

    const bounds = new googleMaps.LatLngBounds();
    mapLocations.withCoords.forEach(({ booking, lat, lng }) => {
      const marker = new googleMaps.Marker({
        position: { lat, lng },
        title: booking.client?.name ?? "Booking",
        icon: {
          path: googleMaps.SymbolPath.CIRCLE,
          scale: 7,
          fillColor: bookingStatusColor(booking.status),
          fillOpacity: 0.9,
          strokeColor: "#1f2937",
          strokeWeight: 1,
        },
      });
      marker.addListener("click", () => {
        handleMapBookingSelect(booking);
        const infoWindow = mapInfoWindowRef.current;
        if (infoWindow) {
          const root = document.createElement("div");
          root.style.display = "flex";
          root.style.flexDirection = "column";
          root.style.gap = "4px";
          root.style.minWidth = "160px";
          const strong = document.createElement("strong");
          strong.textContent = booking.client?.name ?? "Client";
          const span = document.createElement("span");
          span.textContent = `${formatStartTime(booking.starts_at)} • ${shortAddress(booking.address)}`;
          root.append(strong, span);
          infoWindow.setContent(root);
          infoWindow.open({ map, anchor: marker });
        }
      });
      marker.setMap(map);
      mapMarkersRef.current.push(marker);
      bounds.extend({ lat, lng });
    });

    const clustererConstructor =
      (window as any).MarkerClusterer ?? (window as any).markerClusterer?.MarkerClusterer;
    if (clustererConstructor && clustererLoaded) {
      mapClustererRef.current = new clustererConstructor({ map, markers: mapMarkersRef.current });
    }

    map.fitBounds(bounds);
    lastBoundsRef.current = bounds;
  }, [clustererLoaded, handleMapBookingSelect, hasMapKey, mapLocations, mapScriptsLoaded]);

  useEffect(() => {
    if (!mapInstanceRef.current || !(window as any).google?.maps) return;
    (window as any).google.maps.event.trigger(mapInstanceRef.current, "resize");
    if (lastBoundsRef.current) {
      mapInstanceRef.current.fitBounds(lastBoundsRef.current);
    } else {
      mapInstanceRef.current.setCenter(EDMONTON_CENTER);
      mapInstanceRef.current.setZoom(11);
    }
  }, [viewMode]);

  const totalTimelineWidth = (RANGE_END_MINUTES - RANGE_START_MINUTES) * MINUTE_WIDTH;
  const handleRowsScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    if (hoursScrollRef.current) {
      hoursScrollRef.current.scrollLeft = event.currentTarget.scrollLeft;
    }
  }, []);

  const selectedPending = selectedBooking ? isActionPending(selectedBooking.booking_id) : false;

  return (
    <div className="dispatcher-page">
      {hasMapKey ? (
        <>
          <Script
            src={`https://maps.googleapis.com/maps/api/js?key=${mapApiKey}`}
            onLoad={() => setMapScriptsLoaded(true)}
          />
          <Script
            src="https://unpkg.com/@googlemaps/markerclusterer/dist/index.min.js"
            onLoad={() => setClustererLoaded(true)}
          />
        </>
      ) : null}
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
        {toast ? <div className={`inline-alert ${toast.kind}`}>{toast.message}</div> : null}
        {error ? <div className="inline-alert error">{error}</div> : null}
        <div className="dispatcher-metrics">
          <section className="dispatcher-card" aria-label="Today stats">
            <header>
              <h2>Today</h2>
              <span className="muted">Paid revenue</span>
            </header>
            <div className="dispatcher-metric-grid">
              <div>
                <span className="muted">Planned</span>
                <strong>{stats?.planned_count ?? "—"}</strong>
              </div>
              <div>
                <span className="muted">In progress</span>
                <strong>{stats?.in_progress_count ?? "—"}</strong>
              </div>
              <div>
                <span className="muted">Done</span>
                <strong>{stats?.done_count ?? "—"}</strong>
              </div>
              <div>
                <span className="muted">Avg duration</span>
                <strong>
                  {stats?.avg_duration_hours !== null && stats?.avg_duration_hours !== undefined
                    ? `${stats.avg_duration_hours.toFixed(2)}h`
                    : "—"}
                </strong>
              </div>
              <div>
                <span className="muted">Revenue</span>
                <strong>{stats ? formatCurrencyFromCents(stats.revenue_today) : "—"}</strong>
              </div>
            </div>
          </section>
          <section className="dispatcher-card" aria-label="Zone filter">
            <header>
              <h2>Zones</h2>
              <span className="muted">Filter board + stats</span>
            </header>
            <div className="dispatcher-zone-chips" role="group" aria-label="Zone filters">
              {ZONE_OPTIONS.map((zone) => {
                const isActive = selectedZone === zone;
                return (
                  <button
                    key={zone}
                    type="button"
                    className={`dispatcher-zone-chip${isActive ? " active" : ""}`}
                    onClick={() => setSelectedZone(zone)}
                  >
                    {zone}
                  </button>
                );
              })}
            </div>
          </section>
        </div>
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
            <div className="dispatcher-main">
              <div className="dispatcher-view-toggle" role="tablist" aria-label="Timeline map view">
                {(["timeline", "map", "split"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={viewMode === mode}
                    className={`dispatcher-view-button${viewMode === mode ? " active" : ""}`}
                    onClick={() => setViewMode(mode)}
                  >
                    {mode === "timeline" ? "Timeline" : mode === "map" ? "Map" : "Split"}
                  </button>
                ))}
              </div>
              <div className={`dispatcher-view dispatcher-view-${viewMode}`}>
                {board.workers.length > 0 ? (
                  <div
                    className={`dispatcher-panel dispatcher-panel-timeline${
                      viewMode === "map" ? " is-hidden" : ""
                    }`}
                    role="region"
                    aria-label="Dispatcher timeline"
                  >
                    <div className="dispatcher-timeline">
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
                                  className={`dispatcher-row-track${
                                    dragOverWorkerId === worker.worker_id ? " drop-target" : ""
                                  }`}
                                  style={{ minWidth: totalTimelineWidth }}
                                  aria-label={`Timeline for ${worker.display_name}`}
                                  onDragOver={handleDragOver}
                                  onDragEnter={handleDragEnter(worker.worker_id)}
                                  onDragLeave={handleDragLeave}
                                  onDrop={handleDropOnWorker(worker.worker_id)}
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
                                        }${draggingBookingId === booking.booking_id ? " dragging" : ""}`}
                                        style={{
                                          left: `${startOffset * MINUTE_WIDTH}px`,
                                          width: `${width}px`,
                                        }}
                                        onClick={() => focusBooking(booking)}
                                        onDragStart={handleDragStart(booking.booking_id)}
                                        onDragEnd={handleDragEnd}
                                        draggable
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
                  </div>
                ) : null}
                <div
                  className={`dispatcher-panel dispatcher-panel-map${
                    viewMode === "timeline" ? " is-hidden" : ""
                  }`}
                  role="region"
                  aria-label="Dispatcher map"
                >
                  <div className="dispatcher-map-header">
                    <div>
                      <h3>Active bookings map</h3>
                      <p className="muted">Edmonton area view for today.</p>
                    </div>
                    <div className="dispatcher-map-meta">
                      <span className="muted">Missing locations</span>
                      <strong>{board ? mapLocations.missingCount : "—"}</strong>
                    </div>
                  </div>
                  {!hasMapKey ? (
                    <div className="dispatcher-map-unavailable">
                      Map unavailable (missing key).
                    </div>
                  ) : (
                    <div className="dispatcher-map-canvas" ref={mapContainerRef} />
                  )}
                </div>
              </div>
            </div>
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
              <div className="detail dispatcher-route-detail">
                <span className="detail-label">Routes</span>
                <div className="dispatcher-route-stack">
                  <div className="dispatcher-route-row">
                    <div>
                      <span className="dispatcher-route-title">Current assignment</span>
                      <span className="dispatcher-route-subtitle">
                        {currentOriginInfo
                          ? `From ${currentOriginInfo.label} → ${shortAddress(selectedBooking.address)}`
                          : "Origin unavailable"}
                      </span>
                    </div>
                    <div className="dispatcher-route-meta">
                      {currentRoutePending ? (
                        <span className="muted">Estimating...</span>
                      ) : currentRouteEstimate ? (
                        <>
                          <strong>{formatDurationMinutes(currentRouteEstimate.duration_min)}</strong>
                          <span className="muted">{formatDistanceKm(currentRouteEstimate.distance_km)}</span>
                          {currentRouteEstimate.duration_in_traffic_min ? (
                            <span className="muted">
                              Traffic {formatDurationMinutes(currentRouteEstimate.duration_in_traffic_min)}
                            </span>
                          ) : null}
                        </>
                      ) : (
                        <span className="muted">{currentRouteError ?? "Select a booking with locations."}</span>
                      )}
                    </div>
                  </div>
                  <div className="dispatcher-route-row">
                    <div>
                      <span className="dispatcher-route-title">Reassign comparison</span>
                      <span className="dispatcher-route-subtitle">
                        {reassignWorkerName
                          ? `From ${reassignOriginInfo?.label ?? "origin unavailable"}`
                          : "Select a worker to compare"}
                      </span>
                    </div>
                    <div className="dispatcher-route-meta">
                      {reassignRoutePending ? (
                        <span className="muted">Estimating...</span>
                      ) : reassignRouteEstimate ? (
                        <>
                          <strong>{formatDurationMinutes(reassignRouteEstimate.duration_min)}</strong>
                          <span className="muted">{formatDistanceKm(reassignRouteEstimate.distance_km)}</span>
                        </>
                      ) : (
                        <span className="muted">{reassignRouteError ?? "—"}</span>
                      )}
                    </div>
                  </div>
                  {routeDeltaMinutes !== null && reassignWorkerName ? (
                    <div className="dispatcher-route-delta">
                      Assigning to {reassignWorkerName} {routeDeltaMinutes >= 0 ? "adds" : "saves"}{" "}
                      {formatDurationDelta(routeDeltaMinutes)} travel.
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="dispatcher-actions">
                <div className="dispatcher-action-group">
                  <span className="detail-label">Reassign</span>
                  <div className="dispatcher-action-row">
                    <select
                      className="input"
                      value={reassignWorkerId}
                      onChange={(event) => setReassignWorkerId(event.target.value)}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      <option value="">Select worker</option>
                      {(board?.workers ?? []).map((worker) => (
                        <option key={worker.worker_id} value={worker.worker_id}>
                          {worker.display_name || `Worker ${worker.worker_id}`}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn"
                      type="button"
                      disabled={!reassignWorkerId || !isAuthenticated || selectedPending}
                      onClick={() => {
                        if (!reassignWorkerId) return;
                        void handleReassign(selectedBooking.booking_id, Number(reassignWorkerId));
                      }}
                    >
                      Reassign
                    </button>
                  </div>
                </div>
                <div className="dispatcher-action-group">
                  <span className="detail-label">Smart Assignment</span>
                  <div className="dispatcher-action-row dispatcher-smart-actions">
                    <button
                      className="btn btn-secondary"
                      type="button"
                      onClick={() => void fetchSuggestions()}
                      disabled={!isAuthenticated || selectedPending || suggestionsPending}
                    >
                      {suggestionsPending ? "Suggesting..." : "Suggest"}
                    </button>
                    {suggestionsError ? <span className="muted">{suggestionsError}</span> : null}
                  </div>
                  {suggestions.length ? (
                    <ul className="dispatcher-smart-list">
                      {suggestions.map((suggestion) => {
                        const isAssigned = suggestion.worker_id === selectedBooking.assigned_worker?.id;
                        return (
                          <li key={suggestion.worker_id} className="dispatcher-smart-card">
                            <div className="dispatcher-smart-main">
                              <div>
                                <strong>{suggestion.display_name ?? `Worker ${suggestion.worker_id}`}</strong>
                                <div className="dispatcher-smart-meta">
                                  <span className="muted">
                                    {suggestion.eta_min != null
                                      ? `ETA ${formatDurationMinutes(suggestion.eta_min)}`
                                      : "ETA unknown"}
                                  </span>
                                  <span className="dispatcher-smart-score">
                                    Score {suggestion.score_total.toFixed(2)}
                                  </span>
                                </div>
                                <div className="dispatcher-smart-reasons">
                                  {suggestion.reasons.map((reason) => (
                                    <span key={reason} className="dispatcher-smart-reason">
                                      {reason}
                                    </span>
                                  ))}
                                </div>
                              </div>
                              <button
                                className="btn"
                                type="button"
                                disabled={!isAuthenticated || selectedPending || isAssigned}
                                onClick={() => void handleReassign(selectedBooking.booking_id, suggestion.worker_id)}
                              >
                                {isAssigned ? "Assigned" : "Assign"}
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p className="muted">Select suggest to see top available workers.</p>
                  )}
                </div>
                <div className="dispatcher-action-group">
                  <span className="detail-label">Reschedule</span>
                  <div className="dispatcher-action-row">
                    <label className="field">
                      <span>Start</span>
                      <input
                        className="input"
                        type="datetime-local"
                        value={rescheduleStart}
                        onChange={(event) => setRescheduleStart(event.target.value)}
                        disabled={!isAuthenticated || selectedPending}
                      />
                    </label>
                    <label className="field">
                      <span>End</span>
                      <input
                        className="input"
                        type="datetime-local"
                        value={rescheduleEnd}
                        onChange={(event) => setRescheduleEnd(event.target.value)}
                        disabled={!isAuthenticated || selectedPending}
                      />
                    </label>
                  </div>
                  <label className="dispatcher-action-row">
                    <input
                      type="checkbox"
                      checked={rescheduleOverride}
                      onChange={(event) => setRescheduleOverride(event.target.checked)}
                      disabled={!isAuthenticated || selectedPending}
                    />
                    <span className="muted">Override conflicts</span>
                  </label>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => void handleReschedule()}
                    disabled={!isAuthenticated || selectedPending}
                  >
                    Reschedule
                  </button>
                </div>
                <div className="dispatcher-action-group">
                  <span className="detail-label">Status</span>
                  <div className="dispatcher-action-row">
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleStatusUpdate("IN_PROGRESS")}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      Mark in progress
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleStatusUpdate("DONE")}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      Mark done
                    </button>
                  </div>
                </div>
                <div className="dispatcher-action-group">
                  <span className="detail-label">Communication</span>
                  <div className="dispatcher-comm-quick">
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleNotify("client", "call", commTemplateId)}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      Call client
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleNotify("client", "sms", commTemplateId)}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      SMS client
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleNotify("worker", "call", commTemplateId)}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      Call worker
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleNotify("worker", "sms", commTemplateId)}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      SMS worker
                    </button>
                  </div>
                  <div className="dispatcher-action-row dispatcher-comm-template">
                    <label className="field">
                      <span>Target</span>
                      <select
                        className="input"
                        value={commTarget}
                        onChange={(event) => setCommTarget(event.target.value as "client" | "worker")}
                        disabled={!isAuthenticated || selectedPending}
                      >
                        <option value="client">Client</option>
                        <option value="worker">Worker</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>Channel</span>
                      <select
                        className="input"
                        value={commChannel}
                        onChange={(event) => setCommChannel(event.target.value as "sms" | "call")}
                        disabled={!isAuthenticated || selectedPending}
                      >
                        <option value="sms">SMS</option>
                        <option value="call">Call</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>Template</span>
                      <select
                        className="input"
                        value={commTemplateId}
                        onChange={(event) => setCommTemplateId(event.target.value)}
                        disabled={!isAuthenticated || selectedPending}
                      >
                        {DISPATCHER_TEMPLATES.map((template) => (
                          <option key={template.id} value={template.id}>
                            {template.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => void handleNotify(commTarget, commChannel, commTemplateId)}
                      disabled={!isAuthenticated || selectedPending}
                    >
                      Send
                    </button>
                  </div>
                  {commError ? <p className="muted">{commError}</p> : null}
                  <div className="dispatcher-comm-history">
                    <span className="detail-label">Last sent</span>
                    {commAudits.length ? (
                      <ul>
                        {commAudits.map((audit) => (
                          <li key={audit.audit_id}>
                            <span>{formatAuditTime(audit.sent_at)}</span>
                            <span>
                              {audit.channel.toUpperCase()} {audit.target}
                            </span>
                            <span>{audit.template_id}</span>
                            <span className={`dispatcher-comm-status ${audit.status}`}>
                              {audit.status}
                            </span>
                            {audit.error_code ? <span>{audit.error_code}</span> : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted">No communications logged yet.</p>
                    )}
                  </div>
                </div>
                <div className="dispatcher-action-group">
                  <span className="detail-label">Cancel</span>
                  <textarea
                    className="input"
                    rows={3}
                    placeholder="Reason for cancelling"
                    value={cancelReason}
                    onChange={(event) => setCancelReason(event.target.value)}
                    disabled={!isAuthenticated || selectedPending}
                  />
                  <button
                    className="btn danger"
                    type="button"
                    onClick={() => void handleCancel()}
                    disabled={!isAuthenticated || selectedPending}
                  >
                    Cancel booking
                  </button>
                </div>
              </div>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
