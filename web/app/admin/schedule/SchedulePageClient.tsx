"use client";

import { type DragEvent, type MouseEvent, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import AdminNav from "../components/AdminNav";
import {
  ADMIN_STORAGE_PASSWORD_KEY,
  ADMIN_STORAGE_USERNAME_KEY,
  resolveAdminAuthHeaders,
} from "../lib/adminAuth";
import { DEFAULT_FEATURE_CONFIG, DEFAULT_UI_PREFS } from "../lib/adminDefaults";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../lib/featureVisibility";
import { DEFAULT_ORG_TIMEZONE, type OrgSettingsResponse } from "../lib/orgSettings";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const START_HOUR = 8;
const END_HOUR = 18;
const SLOT_MINUTES = 30;
const SLOT_HEIGHT = 28;
const LIST_PAGE_SIZE = 25;

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const WEEKDAY_INDEX: Record<string, number> = {
  Mon: 0,
  Tue: 1,
  Wed: 2,
  Thu: 3,
  Fri: 4,
  Sat: 5,
  Sun: 6,
};

type ScheduleBooking = {
  booking_id: string;
  starts_at: string;
  ends_at: string;
  duration_minutes: number;
  status: string;
  worker_id: number | null;
  worker_name: string | null;
  team_id: number;
  team_name: string | null;
  client_label: string | null;
  address: string | null;
  service_label: string | null;
  price_cents: number | null;
  notes: string | null;
};

type ScheduleResponse = {
  from_date: string;
  to_date: string;
  bookings: ScheduleBooking[];
  total?: number;
  limit?: number | null;
  offset?: number | null;
  query?: string | null;
};

type WorkerTimelineTotals = {
  booked_minutes: number;
  booking_count: number;
  revenue_cents: number;
};

type WorkerTimelineDay = {
  date: string;
  booked_minutes: number;
  booking_count: number;
  revenue_cents: number;
  booking_ids: string[];
};

type WorkerTimelineWorker = {
  worker_id: number;
  name: string;
  team_id: number | null;
  team_name: string | null;
  days: WorkerTimelineDay[];
  totals: WorkerTimelineTotals;
};

type WorkerTimelineResponse = {
  from_date: string;
  to_date: string;
  org_timezone: string;
  days: string[];
  workers: WorkerTimelineWorker[];
  totals: WorkerTimelineTotals;
};

type TeamCalendarDay = {
  date: string;
  bookings: number;
  revenue: number;
  workers_used: number;
};

type TeamCalendarTeam = {
  team_id: number;
  name: string;
  days: TeamCalendarDay[];
};

type TeamCalendarResponse = {
  from_date: string;
  to_date: string;
  org_timezone: string;
  days: string[];
  teams: TeamCalendarTeam[];
};

type AvailabilityBlock = {
  id: number;
  scope_type: "worker" | "team" | "org";
  scope_id: number | null;
  block_type: "vacation" | "sick" | "training" | "holiday";
  starts_at: string;
  ends_at: string;
  reason: string | null;
};

type ToastMessage = {
  message: string;
  kind: "error" | "success";
};

type ClientOption = {
  client_id: string;
  name: string | null;
  email: string;
  phone: string | null;
  address: string | null;
};

type AddressOption = {
  address_id: number;
  label: string;
  address_text: string;
};

type ServiceAddon = {
  addon_id: number;
  name: string;
  price_cents: number;
  active: boolean;
};

type ServiceTypeOption = {
  service_type_id: number;
  name: string;
  active: boolean;
  default_duration_minutes: number;
  base_price_cents: number;
  addons: ServiceAddon[];
};

type AddonOption = {
  addon_id: number;
  name: string;
  price_cents: number;
  default_minutes: number;
};

type RankedWorkerSuggestion = {
  worker_id: number;
  name: string;
  team_id: number;
  team_name: string;
  reasons: string[];
};

type ScheduleSuggestionsResponse = {
  teams: { team_id: number; name: string }[];
  workers: { worker_id: number; name: string; team_id: number; team_name: string }[];
  ranked_workers?: RankedWorkerSuggestion[];
};

type ScheduleOptimizationSuggestion = {
  id: string;
  type: string;
  title: string;
  rationale: string;
  estimated_impact: string | null;
  apply_payload: {
    action: string;
    booking_id: string;
    team_id: number | null;
    starts_at: string;
    ends_at: string;
    candidate_worker_ids: number[];
    worker_id?: number | null;
  };
  severity: "low" | "medium" | "high";
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

function formatDayLabel(day: string, timeZone: string) {
  const formatted = new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone,
  }).format(ymdToDate(day));
  return formatted.replace(",", "");
}

function formatTimeLabel(hour: number) {
  return `${hour.toString().padStart(2, "0")}:00`;
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

function formatDateTimeLabel(value: string, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  });
  return formatter.format(new Date(value));
}

function formatCurrencyFromCents(value: number | null) {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

function formatHoursFromMinutes(minutes: number) {
  if (!minutes) return "—";
  return `${(minutes / 60).toFixed(1)}h`;
}

function formatBookingCount(count: number) {
  if (!count) return "—";
  return `${count} booking${count === 1 ? "" : "s"}`;
}

const DANGEROUS_CSV_PREFIXES = ["=", "+", "-", "@", "\t"];

function sanitizeCsvValue(value: string) {
  if (!value) return "";
  if (DANGEROUS_CSV_PREFIXES.some((prefix) => value.startsWith(prefix))) {
    return `'${value}`;
  }
  return value;
}

function csvEscape(value: string) {
  const sanitized = sanitizeCsvValue(value);
  const escaped = sanitized.replace(/"/g, '""');
  return `"${escaped}"`;
}

function formatNotesForPrint(value: string | null) {
  if (!value) return "—";
  return value.replace(/\n/g, "<br/>");
}

function formatDateTimeInput(date: Date) {
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

function formatBlockType(value: AvailabilityBlock["block_type"]) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function centsFromInput(value: string) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.round(parsed * 100);
}

function minutesFromTime(value: string, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  });
  const parts = formatter.formatToParts(new Date(value));
  const lookup: Record<string, string> = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const hours = parseInt(lookup.hour || "0", 10);
  const minutes = parseInt(lookup.minute || "0", 10);
  return hours * 60 + minutes;
}

function localDayForBooking(value: string, timeZone: string) {
  return formatYMDInTz(new Date(value), timeZone);
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

export default function SchedulePage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [orgSettings, setOrgSettings] = useState<OrgSettingsResponse | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [availabilityBlocks, setAvailabilityBlocks] = useState<AvailabilityBlock[]>([]);
  const [workerTimeline, setWorkerTimeline] = useState<WorkerTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [teamCalendar, setTeamCalendar] = useState<TeamCalendarResponse | null>(null);
  const [teamCalendarLoading, setTeamCalendarLoading] = useState(false);
  const [teamCalendarError, setTeamCalendarError] = useState<string | null>(null);
  const [optimizationSuggestions, setOptimizationSuggestions] = useState<
    ScheduleOptimizationSuggestion[]
  >([]);
  const [optimizationLoading, setOptimizationLoading] = useState(false);
  const [optimizationError, setOptimizationError] = useState<string | null>(null);
  const [expandedSuggestionIds, setExpandedSuggestionIds] = useState<Set<string>>(new Set());
  const [applySuggestion, setApplySuggestion] = useState<ScheduleOptimizationSuggestion | null>(null);
  const [applySubmitting, setApplySubmitting] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [draggingBookingId, setDraggingBookingId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [viewMode, setViewMode] = useState(searchParams.get("view") ?? "week");
  const [listFrom, setListFrom] = useState(searchParams.get("from") ?? "");
  const [listTo, setListTo] = useState(searchParams.get("to") ?? "");
  const [searchQuery, setSearchQuery] = useState(searchParams.get("q") ?? "");
  const [currentPage, setCurrentPage] = useState(() => {
    const raw = Number(searchParams.get("page") ?? "1");
    return Number.isNaN(raw) || raw < 1 ? 1 : raw;
  });
  const [selectedBookingIds, setSelectedBookingIds] = useState<Set<string>>(new Set());
  const [exportRange, setExportRange] = useState<"week" | "month" | "custom">("week");
  const [exportFrom, setExportFrom] = useState("");
  const [exportTo, setExportTo] = useState("");
  const [includeNotes, setIncludeNotes] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);

  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [quickCreateError, setQuickCreateError] = useState<string | null>(null);
  const [quickCreateStart, setQuickCreateStart] = useState("");
  const [quickCreateDuration, setQuickCreateDuration] = useState(120);
  const [durationTouched, setDurationTouched] = useState(false);
  const [quickCreatePrice, setQuickCreatePrice] = useState("");
  const [priceTouched, setPriceTouched] = useState(false);
  const [quickCreateDeposit, setQuickCreateDeposit] = useState("");
  const [prefillApplied, setPrefillApplied] = useState(false);
  const [clientQuery, setClientQuery] = useState("");
  const [clientOptions, setClientOptions] = useState<ClientOption[]>([]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [creatingClient, setCreatingClient] = useState(false);
  const [newClientName, setNewClientName] = useState("");
  const [newClientEmail, setNewClientEmail] = useState("");
  const [newClientPhone, setNewClientPhone] = useState("");
  const [addressOptions, setAddressOptions] = useState<AddressOption[]>([]);
  const [selectedAddressId, setSelectedAddressId] = useState("");
  const [useNewAddress, setUseNewAddress] = useState(false);
  const [newAddressLabel, setNewAddressLabel] = useState("Primary");
  const [newAddressText, setNewAddressText] = useState("");
  const [serviceTypes, setServiceTypes] = useState<ServiceTypeOption[]>([]);
  const [selectedServiceTypeId, setSelectedServiceTypeId] = useState("");
  const [selectedAddonIds, setSelectedAddonIds] = useState<Set<number>>(new Set());
  const [addonOptions, setAddonOptions] = useState<AddonOption[]>([]);
  const [workerSuggestions, setWorkerSuggestions] = useState<RankedWorkerSuggestion[]>([]);
  const [availableWorkers, setAvailableWorkers] = useState<RankedWorkerSuggestion[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState("");

  const orgTimezone = orgSettings?.timezone ?? DEFAULT_ORG_TIMEZONE;
  const defaultDate = useMemo(() => formatYMDInTz(new Date(), orgTimezone), [orgTimezone]);
  const defaultWeekRange = useMemo(() => {
    const start = weekStartFromDay(defaultDate, orgTimezone);
    return { from: start, to: addDaysYMD(start, 6, orgTimezone) };
  }, [defaultDate, orgTimezone]);
  const defaultMonthRange = useMemo(
    () => monthRangeForDay(defaultDate, orgTimezone),
    [defaultDate, orgTimezone]
  );

  const [selectedDate, setSelectedDate] = useState<string>(searchParams.get("date") ?? defaultDate);
  const [teamFilter, setTeamFilter] = useState<string>(searchParams.get("team_id") ?? "");
  const [workerFilter, setWorkerFilter] = useState<string>(searchParams.get("worker_id") ?? "");
  const [statusFilter, setStatusFilter] = useState<string>(searchParams.get("status") ?? "");

  const { headers: authHeaders, hasCredentials } = useMemo(
    () => resolveAdminAuthHeaders(username, password),
    [username, password]
  );
  const isAuthenticated = hasCredentials;
  const permissionKeys = profile?.permissions ?? [];
  const canAssign =
    permissionKeys.includes("bookings.assign") || permissionKeys.includes("bookings.edit");
  const canCreate = permissionKeys.includes("bookings.edit");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const scheduleVisible = visibilityReady
    ? isVisible("module.schedule", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const optimizationVisible = visibilityReady
    ? isVisible("schedule.optimization", permissionKeys, featureOverrides, hiddenKeys)
    : false;
  const isListView = viewMode === "list";
  const isMonthView = viewMode === "month";
  const isDayView = viewMode === "day";
  const isTimelineView = viewMode === "timeline";
  const isTeamView = viewMode === "teams";
  const isListLikeView = isListView || isMonthView;
  const showCalendar = viewMode === "week" || isDayView;
  const showWeekControls = showCalendar || isTimelineView || isTeamView;
  const viewTitle = isListView
    ? "Schedule List"
    : isMonthView
      ? "Month Schedule"
      : isDayView
        ? "Day Schedule"
        : isTimelineView
          ? "Worker Timeline"
          : isTeamView
            ? "Team Calendar"
            : "Week Schedule";
  const viewSubtitle = isListLikeView
    ? "List view with filters, bulk actions, and exports."
    : isTimelineView
      ? "Weekly utilization by worker in the organization timezone."
      : isTeamView
        ? "Daily booking volume, workers, and revenue by team."
        : "Dispatcher view in the organization timezone.";
  const navigationStep = isDayView ? 1 : 7;
  const applyCandidateCount = applySuggestion?.apply_payload.candidate_worker_ids.length ?? 0;
  const optimizationRange = useMemo(() => {
    if (isListLikeView) {
      if (!listFrom || !listTo) return null;
      return { from: listFrom, to: listTo };
    }
    if (isDayView) {
      return { from: selectedDate, to: selectedDate };
    }
    const weekStart = weekStartFromDay(selectedDate, orgTimezone);
    return { from: weekStart, to: addDaysYMD(weekStart, 6, orgTimezone) };
  }, [isDayView, isListLikeView, listFrom, listTo, orgTimezone, selectedDate]);

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
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
        featureKey: "module.settings",
      },
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

  const showToast = useCallback((message: string, kind: "error" | "success" = "error") => {
    setToast({ message, kind });
  }, []);

  const toggleSuggestionDetails = useCallback((suggestionId: string) => {
    setExpandedSuggestionIds((previous) => {
      const next = new Set(previous);
      if (next.has(suggestionId)) {
        next.delete(suggestionId);
      } else {
        next.add(suggestionId);
      }
      return next;
    });
  }, []);

  const refreshSchedule = useCallback(() => {
    setRefreshToken((value) => value + 1);
  }, []);

  const openApplyDialog = useCallback((suggestion: ScheduleOptimizationSuggestion) => {
    setApplySuggestion(suggestion);
    setApplyError(null);
  }, []);

  const closeApplyDialog = useCallback(() => {
    if (applySubmitting) return;
    setApplySuggestion(null);
    setApplyError(null);
  }, [applySubmitting]);

  const handleApplySuggestion = useCallback(async () => {
    if (!applySuggestion) return;
    const candidateIds = applySuggestion.apply_payload.candidate_worker_ids;
    if (!candidateIds.length) {
      setApplyError("No candidate workers available for this suggestion.");
      return;
    }
    setApplySubmitting(true);
    setApplyError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/schedule/optimization/apply`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify({
          suggestion_id: applySuggestion.id,
          apply_payload: {
            ...applySuggestion.apply_payload,
            worker_id: candidateIds[0],
          },
        }),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        const detail = errorPayload?.detail;
        const errorReason = errorPayload?.errors?.[0]?.reason;
        const message =
          typeof detail === "string"
            ? detail
            : detail?.message || detail?.reason || "Failed to apply suggestion.";
        setApplyError(errorReason ? `${message} (${errorReason})` : message);
        return;
      }
      await response.json();
      showToast("Suggestion applied.", "success");
      setApplySuggestion(null);
      refreshSchedule();
    } catch (fetchError) {
      setApplyError(fetchError instanceof Error ? fetchError.message : "Failed to apply suggestion.");
    } finally {
      setApplySubmitting(false);
    }
  }, [applySuggestion, authHeaders, refreshSchedule, showToast]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(ADMIN_STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(ADMIN_STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (searchParams.get("date")) {
      setSelectedDate(searchParams.get("date") as string);
      return;
    }
    setSelectedDate(defaultDate);
  }, [defaultDate, searchParams]);

  useEffect(() => {
    setTeamFilter(searchParams.get("team_id") ?? "");
    setWorkerFilter(searchParams.get("worker_id") ?? "");
    setStatusFilter(searchParams.get("status") ?? "");
  }, [searchParams]);

  useEffect(() => {
    const viewParam = searchParams.get("view") ?? "week";
    setViewMode(viewParam);
    const rangeDefaults = viewParam === "month" ? defaultMonthRange : defaultWeekRange;
    setListFrom(searchParams.get("from") ?? rangeDefaults.from);
    setListTo(searchParams.get("to") ?? rangeDefaults.to);
    setSearchQuery(searchParams.get("q") ?? "");
    const rawPage = Number(searchParams.get("page") ?? "1");
    setCurrentPage(Number.isNaN(rawPage) || rawPage < 1 ? 1 : rawPage);
  }, [defaultMonthRange, defaultWeekRange, searchParams]);

  const updateQuery = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (!value) {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const loadProfile = useCallback(async () => {
    if (!hasCredentials) return;
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
  }, [authHeaders, hasCredentials]);

  const loadFeatureConfig = useCallback(async () => {
    if (!hasCredentials) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as FeatureConfigResponse;
        setFeatureConfig(data);
      } else {
        setFeatureConfig(DEFAULT_FEATURE_CONFIG);
      }
    } catch (error) {
      console.error("Failed to load module settings:", error);
      setFeatureConfig(DEFAULT_FEATURE_CONFIG);
    }
  }, [authHeaders, hasCredentials]);

  const loadUiPrefs = useCallback(async () => {
    if (!hasCredentials) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as UiPrefsResponse;
        setUiPrefs(data);
      } else {
        setUiPrefs(DEFAULT_UI_PREFS);
      }
    } catch (error) {
      console.error("Failed to load UI preferences:", error);
      setUiPrefs(DEFAULT_UI_PREFS);
    }
  }, [authHeaders, hasCredentials]);

  const loadOrgSettings = useCallback(async () => {
    if (!hasCredentials) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/org`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as OrgSettingsResponse;
      setOrgSettings(data);
    } else {
      setOrgSettings(null);
    }
  }, [authHeaders, hasCredentials]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadOrgSettings();
  }, [isAuthenticated, loadFeatureConfig, loadOrgSettings, loadProfile, loadUiPrefs]);

  useEffect(() => {
    if (!isAuthenticated || !scheduleVisible) return;
    fetch(`${API_BASE}/v1/admin/service-types`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load service types");
        }
        return response.json();
      })
      .then((payload: ServiceTypeOption[]) => {
        setServiceTypes(payload.filter((service) => service.active));
      })
      .catch(() => {
        setServiceTypes([]);
      });
  }, [authHeaders, isAuthenticated, scheduleVisible]);

  useEffect(() => {
    if (!isAuthenticated || !canCreate) return;
    fetch(`${API_BASE}/v1/admin/schedule/addons`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load addons");
        }
        return response.json();
      })
      .then((payload: AddonOption[]) => {
        setAddonOptions(payload);
      })
      .catch(() => {
        setAddonOptions([]);
      });
  }, [authHeaders, canCreate, isAuthenticated]);

  useEffect(() => {
    if (!quickCreateOpen) return;
    if (creatingClient) {
      setClientOptions([]);
      return;
    }
    const trimmed = clientQuery.trim();
    if (!trimmed) {
      setClientOptions([]);
      return;
    }
    const timeout = window.setTimeout(() => {
      fetch(`${API_BASE}/v1/admin/clients?q=${encodeURIComponent(trimmed)}`, {
        headers: authHeaders,
        cache: "no-store",
      })
        .then(async (response) => {
          if (!response.ok) {
            const message = await response.text();
            throw new Error(message || "Failed to load clients");
          }
          return response.json();
        })
        .then((payload: ClientOption[]) => {
          setClientOptions(payload);
        })
        .catch(() => {
          setClientOptions([]);
        });
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [authHeaders, clientQuery, creatingClient, quickCreateOpen]);

  useEffect(() => {
    if (!selectedClientId || creatingClient || !quickCreateOpen) {
      setAddressOptions([]);
      setSelectedAddressId("");
      return;
    }
    fetch(`${API_BASE}/v1/admin/clients/${selectedClientId}/addresses`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load addresses");
        }
        return response.json();
      })
      .then((payload: AddressOption[]) => {
        setAddressOptions(payload);
        if (payload.length && !selectedAddressId) {
          setSelectedAddressId(String(payload[0].address_id));
        }
      })
      .catch(() => {
        setAddressOptions([]);
      });
  }, [authHeaders, creatingClient, quickCreateOpen, selectedAddressId, selectedClientId]);

  useEffect(() => {
    const match = serviceTypes.find(
      (service) => String(service.service_type_id) === selectedServiceTypeId
    );
    if (!match) return;
    if (!durationTouched) {
      setQuickCreateDuration(match.default_duration_minutes);
    }
    if (!priceTouched) {
      setQuickCreatePrice((match.base_price_cents / 100).toFixed(2));
    }
  }, [durationTouched, priceTouched, selectedServiceTypeId, serviceTypes]);

  useEffect(() => {
    if (!quickCreateOpen || !quickCreateStart || !quickCreateDuration) {
      setWorkerSuggestions([]);
      setAvailableWorkers([]);
      return;
    }
    const startDate = parseDateTimeLocal(quickCreateStart);
    if (!startDate) return;
    const params = new URLSearchParams({
      starts_at: startDate.toISOString(),
      duration_min: String(quickCreateDuration),
    });
    if (!useNewAddress && selectedAddressId) {
      params.set("address_id", selectedAddressId);
    }
    if (selectedServiceTypeId) {
      params.set("service_type_id", selectedServiceTypeId);
    }
    fetch(`${API_BASE}/v1/admin/schedule/suggestions?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load suggestions");
        }
        return response.json();
      })
      .then((payload: ScheduleSuggestionsResponse) => {
        const ranked = payload.ranked_workers?.length
          ? payload.ranked_workers
          : payload.workers.map((worker) => ({ ...worker, reasons: ["available"] }));
        setWorkerSuggestions(ranked);
        setAvailableWorkers(ranked);
      })
      .catch(() => {
        setWorkerSuggestions([]);
        setAvailableWorkers([]);
      });
  }, [
    authHeaders,
    quickCreateDuration,
    quickCreateOpen,
    quickCreateStart,
    selectedAddressId,
    selectedServiceTypeId,
    useNewAddress,
  ]);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (!scheduleVisible) return;
    if (isTeamView) return;
    if (isListLikeView && (!listFrom || !listTo)) return;
    setLoading(true);
    setError(null);
    const weekStart = weekStartFromDay(selectedDate, orgTimezone);
    const weekEnd = addDaysYMD(weekStart, 6, orgTimezone);
    const rangeFrom = isListLikeView ? listFrom : isDayView ? selectedDate : weekStart;
    const rangeTo = isListLikeView ? listTo : isDayView ? selectedDate : weekEnd;
    const params = new URLSearchParams({
      from: rangeFrom,
      to: rangeTo,
    });
    if (teamFilter) params.set("team_id", teamFilter);
    if (workerFilter) params.set("worker_id", workerFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (isListLikeView) {
      params.set("limit", String(LIST_PAGE_SIZE));
      params.set("offset", String((currentPage - 1) * LIST_PAGE_SIZE));
      if (searchQuery) params.set("q", searchQuery);
    }

    fetch(`${API_BASE}/v1/admin/schedule?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load schedule");
        }
        return response.json();
      })
      .then((payload: ScheduleResponse) => {
        setSchedule(payload);
      })
      .catch((fetchError) => {
        setSchedule(null);
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load schedule");
      })
      .finally(() => setLoading(false));
  }, [
    authHeaders,
    isAuthenticated,
    isDayView,
    isListLikeView,
    orgTimezone,
    refreshToken,
    scheduleVisible,
    currentPage,
    listFrom,
    listTo,
    searchQuery,
    selectedDate,
    statusFilter,
    teamFilter,
    workerFilter,
    isTeamView,
  ]);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (!scheduleVisible || !optimizationVisible) return;
    if (!optimizationRange) {
      setOptimizationSuggestions([]);
      return;
    }
    setOptimizationLoading(true);
    setOptimizationError(null);
    const params = new URLSearchParams({
      from: optimizationRange.from,
      to: optimizationRange.to,
    });
    if (teamFilter) params.set("team_id", teamFilter);
    if (workerFilter) params.set("worker_id", workerFilter);
    fetch(`${API_BASE}/v1/admin/schedule/optimization?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load optimization suggestions");
        }
        return response.json();
      })
      .then((payload: ScheduleOptimizationSuggestion[]) => {
        setOptimizationSuggestions(payload);
      })
      .catch((fetchError) => {
        setOptimizationSuggestions([]);
        setOptimizationError(
          fetchError instanceof Error
            ? fetchError.message
            : "Failed to load optimization suggestions"
        );
      })
      .finally(() => setOptimizationLoading(false));
  }, [
    authHeaders,
    isAuthenticated,
    optimizationRange,
    optimizationVisible,
    refreshToken,
    scheduleVisible,
    teamFilter,
    workerFilter,
  ]);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (!scheduleVisible) return;
    if (!isTimelineView) return;
    setTimelineLoading(true);
    setTimelineError(null);
    const weekStartDate = weekStartFromDay(selectedDate, orgTimezone);
    const weekEndDate = addDaysYMD(weekStartDate, 6, orgTimezone);
    const params = new URLSearchParams({
      from: weekStartDate,
      to: weekEndDate,
    });
    if (teamFilter) params.set("team_id", teamFilter);
    if (workerFilter) params.set("worker_id", workerFilter);
    if (statusFilter) params.set("status", statusFilter);
    fetch(`${API_BASE}/v1/admin/schedule/worker_timeline?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load worker timeline");
        }
        return response.json();
      })
      .then((payload: WorkerTimelineResponse) => {
        setWorkerTimeline(payload);
      })
      .catch((fetchError) => {
        setWorkerTimeline(null);
        setTimelineError(
          fetchError instanceof Error ? fetchError.message : "Failed to load worker timeline"
        );
      })
      .finally(() => setTimelineLoading(false));
  }, [
    authHeaders,
    isAuthenticated,
    isTimelineView,
    orgTimezone,
    refreshToken,
    scheduleVisible,
    selectedDate,
    statusFilter,
    teamFilter,
    workerFilter,
  ]);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (!scheduleVisible) return;
    if (!isTeamView) return;
    setTeamCalendarLoading(true);
    setTeamCalendarError(null);
    const weekStartDate = weekStartFromDay(selectedDate, orgTimezone);
    const weekEndDate = addDaysYMD(weekStartDate, 6, orgTimezone);
    const params = new URLSearchParams({
      from: weekStartDate,
      to: weekEndDate,
    });
    if (teamFilter) params.set("team_id", teamFilter);
    if (statusFilter) params.set("status", statusFilter);
    fetch(`${API_BASE}/v1/admin/schedule/team_calendar?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load team calendar");
        }
        return response.json();
      })
      .then((payload: TeamCalendarResponse) => {
        setTeamCalendar(payload);
      })
      .catch((fetchError) => {
        setTeamCalendar(null);
        setTeamCalendarError(
          fetchError instanceof Error ? fetchError.message : "Failed to load team calendar"
        );
      })
      .finally(() => setTeamCalendarLoading(false));
  }, [
    authHeaders,
    isAuthenticated,
    isTeamView,
    orgTimezone,
    refreshToken,
    scheduleVisible,
    selectedDate,
    statusFilter,
    teamFilter,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !scheduleVisible) return;
    if (!showCalendar) return;
    const weekStartDate = weekStartFromDay(selectedDate, orgTimezone);
    const rangeStart = buildOrgZonedInstant(weekStartDate, 0, orgTimezone);
    const rangeEnd = buildOrgZonedInstant(addDaysYMD(weekStartDate, 7, orgTimezone), 0, orgTimezone);
    const params = new URLSearchParams({
      from: rangeStart.toISOString(),
      to: rangeEnd.toISOString(),
    });
    fetch(`${API_BASE}/v1/admin/availability-blocks?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load availability blocks");
        }
        return response.json();
      })
      .then((payload: AvailabilityBlock[]) => {
        setAvailabilityBlocks(Array.isArray(payload) ? payload : []);
      })
      .catch(() => {
        setAvailabilityBlocks([]);
      });
  }, [
    authHeaders,
    isAuthenticated,
    orgTimezone,
    refreshToken,
    scheduleVisible,
    selectedDate,
    showCalendar,
  ]);

  useEffect(() => {
    if (!schedule) {
      setSelectedBookingIds(new Set());
      return;
    }
    setSelectedBookingIds((current) => {
      const activeIds = new Set(schedule.bookings.map((booking) => booking.booking_id));
      const next = new Set(Array.from(current).filter((id) => activeIds.has(id)));
      if (next.size === current.size) return current;
      return next;
    });
  }, [schedule, viewMode]);

  const weekStart = useMemo(() => weekStartFromDay(selectedDate, orgTimezone), [selectedDate, orgTimezone]);
  const weekDays = useMemo(
    () => WEEKDAY_LABELS.map((_, index) => addDaysYMD(weekStart, index, orgTimezone)),
    [orgTimezone, weekStart]
  );
  useEffect(() => {
    if (exportRange === "custom") {
      if (!exportFrom) setExportFrom(defaultWeekRange.from);
      if (!exportTo) setExportTo(defaultWeekRange.to);
      return;
    }
    if (exportRange === "month") {
      setExportFrom(defaultMonthRange.from);
      setExportTo(defaultMonthRange.to);
      return;
    }
    setExportFrom(weekStart);
    setExportTo(addDaysYMD(weekStart, 6, orgTimezone));
  }, [
    defaultMonthRange.from,
    defaultMonthRange.to,
    defaultWeekRange.from,
    defaultWeekRange.to,
    exportFrom,
    exportRange,
    exportTo,
    orgTimezone,
    weekStart,
  ]);
  const visibleDays = useMemo(() => {
    if (isDayView) return [selectedDate];
    return weekDays;
  }, [isDayView, selectedDate, weekDays]);
  const timelineDays = useMemo(() => {
    if (workerTimeline?.days?.length) return workerTimeline.days;
    return weekDays;
  }, [weekDays, workerTimeline]);
  const teamCalendarDays = useMemo(() => {
    if (teamCalendar?.days?.length) return teamCalendar.days;
    return weekDays;
  }, [teamCalendar, weekDays]);

  const timeSlots = useMemo(() => {
    const slots: number[] = [];
    for (let hour = START_HOUR; hour <= END_HOUR; hour += 1) {
      slots.push(hour);
    }
    return slots;
  }, []);

  const dayMinutes = (END_HOUR - START_HOUR) * 60;
  const gridHeight = (dayMinutes / SLOT_MINUTES) * SLOT_HEIGHT;

  const bookingsByDay = useMemo(() => {
    const mapping = new Map<string, ScheduleBooking[]>();
    if (!schedule) return mapping;
    for (const day of visibleDays) {
      mapping.set(day, []);
    }
    for (const booking of schedule.bookings) {
      const bookingDay = localDayForBooking(booking.starts_at, orgTimezone);
      if (!mapping.has(bookingDay)) continue;
      mapping.get(bookingDay)?.push(booking);
    }
    mapping.forEach((entries) =>
      entries.sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
    );
    return mapping;
  }, [orgTimezone, schedule, visibleDays]);

  const bookingWarnings = useMemo(() => {
    const mapping = new Map<string, string[]>();
    if (!schedule || availabilityBlocks.length === 0) return mapping;
    for (const booking of schedule.bookings) {
      const bookingStart = new Date(booking.starts_at).getTime();
      const bookingEnd = new Date(booking.ends_at).getTime();
      const matches = availabilityBlocks.filter((block) => {
        if (block.scope_type === "worker" && booking.worker_id !== block.scope_id) return false;
        if (block.scope_type === "team" && booking.team_id !== block.scope_id) return false;
        const blockStart = new Date(block.starts_at).getTime();
        const blockEnd = new Date(block.ends_at).getTime();
        return bookingStart < blockEnd && bookingEnd > blockStart;
      });
      if (!matches.length) continue;
      mapping.set(
        booking.booking_id,
        matches.map((block) => {
          const typeLabel = formatBlockType(block.block_type);
          return `Blocked: ${typeLabel}${block.reason ? ` — ${block.reason}` : ""}`;
        })
      );
    }
    return mapping;
  }, [availabilityBlocks, schedule]);

  const workerOptions = useMemo(() => {
    const map = new Map<number, string>();
    schedule?.bookings.forEach((booking) => {
      if (booking.worker_id && booking.worker_name) {
        map.set(booking.worker_id, booking.worker_name);
      }
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [schedule]);

  const teamOptions = useMemo(() => {
    const map = new Map<number, string>();
    schedule?.bookings.forEach((booking) => {
      if (booking.team_id) {
        map.set(booking.team_id, booking.team_name ?? `Team ${booking.team_id}`);
      }
    });
    teamCalendar?.teams.forEach((team) => {
      map.set(team.team_id, team.name);
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [schedule, teamCalendar]);

  const selectedServiceType = useMemo(
    () => serviceTypes.find((service) => String(service.service_type_id) === selectedServiceTypeId),
    [selectedServiceTypeId, serviceTypes]
  );

  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    schedule?.bookings.forEach((booking) => {
      if (booking.status) set.add(booking.status);
    });
    return Array.from(set.values()).sort();
  }, [schedule]);

  const listBookings = schedule?.bookings ?? [];
  const totalBookings = schedule?.total ?? listBookings.length;
  const totalPages = Math.max(1, Math.ceil(totalBookings / LIST_PAGE_SIZE));
  const currentRangeStart = totalBookings === 0 ? 0 : (currentPage - 1) * LIST_PAGE_SIZE + 1;
  const currentRangeEnd = Math.min(totalBookings, currentPage * LIST_PAGE_SIZE);
  const allVisibleSelected =
    listBookings.length > 0 && listBookings.every((booking) => selectedBookingIds.has(booking.booking_id));
  const selectedBookings =
    selectedBookingIds.size > 0
      ? listBookings.filter((booking) => selectedBookingIds.has(booking.booking_id))
      : listBookings;

  const timelineTotalsByDay = useMemo(() => {
    const map = new Map<string, WorkerTimelineTotals>();
    if (!workerTimeline) return map;
    for (const day of timelineDays) {
      map.set(day, { booked_minutes: 0, booking_count: 0, revenue_cents: 0 });
    }
    workerTimeline.workers.forEach((worker) => {
      worker.days.forEach((dayEntry) => {
        const current = map.get(dayEntry.date);
        if (!current) return;
        current.booked_minutes += dayEntry.booked_minutes;
        current.booking_count += dayEntry.booking_count;
        current.revenue_cents += dayEntry.revenue_cents;
      });
    });
    return map;
  }, [timelineDays, workerTimeline]);

  const timelineAvailableMinutes = timelineDays.length * (END_HOUR - START_HOUR) * 60;
  const exportRangeLabel = exportFrom && exportTo ? `${exportFrom} → ${exportTo}` : "range";
  const exportFiltersLabel = useMemo(() => {
    const filters: string[] = [];
    if (teamFilter) filters.push(`Team ${teamFilter}`);
    if (workerFilter) filters.push(`Worker ${workerFilter}`);
    if (statusFilter) filters.push(`Status ${statusFilter}`);
    if (searchQuery) filters.push(`Search "${searchQuery}"`);
    return filters.length ? `Filters: ${filters.join(", ")}` : "No filters applied.";
  }, [searchQuery, statusFilter, teamFilter, workerFilter]);

  const buildCsvContent = useCallback(
    (bookings: ScheduleBooking[], includeNotesColumn: boolean) => {
      const header = [
        "Date/Time",
        "Booking ID",
        "Status",
        "Client",
        "Address",
        "Service",
        "Worker",
        "Team",
        "Duration (min)",
        "Amount",
      ];
      if (includeNotesColumn) header.push("Notes");

      const rows = bookings.map((booking) => {
        const baseRow = [
          formatDateTimeLabel(booking.starts_at, orgTimezone),
          booking.booking_id,
          booking.status,
          booking.client_label ?? "",
          booking.address ?? "",
          booking.service_label ?? "",
          booking.worker_name ?? "",
          booking.team_name ?? "",
          String(booking.duration_minutes ?? ""),
          booking.price_cents !== null ? formatCurrencyFromCents(booking.price_cents) : "",
        ];
        if (includeNotesColumn) {
          baseRow.push(booking.notes ?? "");
        }
        return baseRow;
      });
      return [header, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n");
    },
    [orgTimezone]
  );

  const downloadCsv = useCallback((csv: string, filename: string) => {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, []);

  const openPrintView = useCallback(
    (bookings: ScheduleBooking[], title: string, includeNotesColumn: boolean) => {
      const printable = bookings
        .map((booking) => {
          const worker = booking.worker_name ?? "Unassigned";
          const team = booking.team_name ?? "—";
          return `<tr>
            <td>${formatDateTimeLabel(booking.starts_at, orgTimezone)}</td>
            <td>${booking.booking_id}</td>
            <td>${booking.status}</td>
            <td>${booking.client_label ?? "—"}</td>
            <td>${booking.address ?? "—"}</td>
            <td>${booking.service_label ?? "—"}</td>
            <td>${worker}<br/><span class="muted">${team}</span></td>
            <td>${booking.duration_minutes ?? "—"}</td>
            <td>${booking.price_cents !== null ? formatCurrencyFromCents(booking.price_cents) : "—"}</td>
            ${
              includeNotesColumn
                ? `<td>${formatNotesForPrint(booking.notes)}</td>`
                : ""
            }
          </tr>`;
        })
        .join("");
      const printWindow = window.open("", "schedule-print");
      if (!printWindow) {
        showToast("Unable to open print dialog.");
        return;
      }
      printWindow.document.write(`
        <html>
          <head>
            <title>${title}</title>
            <style>
              body { font-family: "Inter", sans-serif; padding: 24px; color: #0f172a; }
              h1 { font-size: 20px; margin-bottom: 12px; }
              table { width: 100%; border-collapse: collapse; font-size: 12px; }
              th, td { border: 1px solid #e2e8f0; padding: 8px; text-align: left; vertical-align: top; }
              th { background: #f8fafc; }
              .muted { color: #64748b; font-size: 11px; }
              @media print {
                body { padding: 0; }
                h1 { margin-top: 0; }
              }
            </style>
          </head>
          <body>
            <h1>${title}</h1>
            <table>
              <thead>
                <tr>
                  <th>Date/Time</th>
                  <th>Booking ID</th>
                  <th>Status</th>
                  <th>Client</th>
                  <th>Address</th>
                  <th>Service</th>
                  <th>Worker/Team</th>
                  <th>Duration (min)</th>
                  <th>Amount</th>
                  ${includeNotesColumn ? "<th>Notes</th>" : ""}
                </tr>
              </thead>
              <tbody>${printable}</tbody>
            </table>
          </body>
        </html>
      `);
      printWindow.document.close();
      printWindow.focus();
      printWindow.print();
    },
    [orgTimezone, showToast]
  );

  const fetchScheduleBookings = useCallback(
    async (from: string, to: string) => {
      const collected: ScheduleBooking[] = [];
      const limit = 500;
      let offset = 0;
      while (true) {
        const params = new URLSearchParams({
          from,
          to,
          limit: String(limit),
          offset: String(offset),
        });
        if (teamFilter) params.set("team_id", teamFilter);
        if (workerFilter) params.set("worker_id", workerFilter);
        if (statusFilter) params.set("status", statusFilter);
        if (searchQuery) params.set("q", searchQuery);
        const response = await fetch(`${API_BASE}/v1/admin/schedule?${params.toString()}`, {
          headers: authHeaders,
          cache: "no-store",
        });
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load schedule export");
        }
        const payload = (await response.json()) as ScheduleResponse;
        collected.push(...payload.bookings);
        const total = payload.total ?? collected.length;
        if (payload.bookings.length < limit || collected.length >= total) {
          break;
        }
        offset += limit;
      }
      return collected;
    },
    [authHeaders, searchQuery, statusFilter, teamFilter, workerFilter]
  );

  const handleRangeExportCsv = useCallback(async () => {
    if (!isAuthenticated) {
      showToast("Save credentials to export.");
      return;
    }
    if (!exportFrom || !exportTo) {
      showToast("Select an export date range.");
      return;
    }
    if (exportFrom > exportTo) {
      showToast("Export start date must be before the end date.");
      return;
    }
    setExportLoading(true);
    try {
      const bookings = await fetchScheduleBookings(exportFrom, exportTo);
      if (!bookings.length) {
        showToast("No bookings found for this range.");
        return;
      }
      const csv = buildCsvContent(bookings, includeNotes);
      downloadCsv(csv, `schedule-${exportFrom}-to-${exportTo}.csv`);
    } catch (exportError) {
      showToast(exportError instanceof Error ? exportError.message : "Export failed");
    } finally {
      setExportLoading(false);
    }
  }, [
    buildCsvContent,
    downloadCsv,
    exportFrom,
    exportTo,
    fetchScheduleBookings,
    includeNotes,
    isAuthenticated,
    showToast,
  ]);

  const handleRangePrint = useCallback(async () => {
    if (!isAuthenticated) {
      showToast("Save credentials to print.");
      return;
    }
    if (!exportFrom || !exportTo) {
      showToast("Select an export date range.");
      return;
    }
    if (exportFrom > exportTo) {
      showToast("Export start date must be before the end date.");
      return;
    }
    setExportLoading(true);
    try {
      const bookings = await fetchScheduleBookings(exportFrom, exportTo);
      if (!bookings.length) {
        showToast("No bookings found for this range.");
        return;
      }
      openPrintView(bookings, `Schedule Export (${exportRangeLabel})`, includeNotes);
    } catch (exportError) {
      showToast(exportError instanceof Error ? exportError.message : "Print failed");
    } finally {
      setExportLoading(false);
    }
  }, [
    exportFrom,
    exportRangeLabel,
    exportTo,
    fetchScheduleBookings,
    includeNotes,
    isAuthenticated,
    openPrintView,
    showToast,
  ]);

  const handleDrop = useCallback(
    async (event: DragEvent<HTMLDivElement>, day: string) => {
      event.preventDefault();
      if (!schedule || !canAssign) return;
      const bookingId = event.dataTransfer.getData("text/plain");
      if (!bookingId) return;
      const booking = schedule.bookings.find((item) => item.booking_id === bookingId);
      if (!booking) return;

      const rect = event.currentTarget.getBoundingClientRect();
      const offsetY = Math.max(0, event.clientY - rect.top);
      const rawMinutes = Math.round(offsetY / SLOT_HEIGHT) * SLOT_MINUTES;
      const minutesFromStart = Math.min(Math.max(rawMinutes, 0), dayMinutes);
      const minutes = START_HOUR * 60 + minutesFromStart;
      const newStart = buildOrgZonedInstant(day, minutes, orgTimezone);
      const newEnd = new Date(newStart.getTime() + booking.duration_minutes * 60000);

      const previous = booking;
      const optimistic: ScheduleBooking = {
        ...booking,
        starts_at: newStart.toISOString(),
        ends_at: newEnd.toISOString(),
      };

      setSchedule((current) => {
        if (!current) return current;
        return {
          ...current,
          bookings: current.bookings.map((item) =>
            item.booking_id === bookingId ? optimistic : item
          ),
        };
      });

      try {
        const response = await fetch(`${API_BASE}/v1/admin/bookings/${bookingId}`, {
          method: "PATCH",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            starts_at: newStart.toISOString(),
            ends_at: newEnd.toISOString(),
          }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          const message =
            payload?.detail?.message || payload?.detail || response.statusText || "Update failed";
          throw new Error(message);
        }
        const updated = (await response.json()) as ScheduleBooking;
        setSchedule((current) => {
          if (!current) return current;
          return {
            ...current,
            bookings: current.bookings.map((item) =>
              item.booking_id === bookingId ? updated : item
            ),
          };
        });
        showToast("Booking updated", "success");
      } catch (fetchError) {
        setSchedule((current) => {
          if (!current) return current;
          return {
            ...current,
            bookings: current.bookings.map((item) =>
              item.booking_id === bookingId ? previous : item
            ),
          };
        });
        showToast(fetchError instanceof Error ? fetchError.message : "Update failed");
      }
    },
    [authHeaders, canAssign, dayMinutes, orgTimezone, schedule, showToast]
  );

  const handleViewChange = useCallback(
    (nextView: string) => {
      const updates: Record<string, string> = { view: nextView };
      if (nextView === "list" || nextView === "month") {
        const rangeDefaults = nextView === "month" ? defaultMonthRange : defaultWeekRange;
        updates.from = listFrom || rangeDefaults.from;
        updates.to = listTo || rangeDefaults.to;
        updates.page = "1";
      } else {
        updates.from = "";
        updates.to = "";
        updates.q = "";
        updates.page = "";
      }
      updateQuery(updates);
    },
    [defaultMonthRange, defaultWeekRange, listFrom, listTo, updateQuery]
  );

  const toggleSelectAll = useCallback(() => {
    setSelectedBookingIds((current) => {
      if (listBookings.length === 0) return current;
      if (allVisibleSelected) {
        return new Set();
      }
      return new Set(listBookings.map((booking) => booking.booking_id));
    });
  }, [allVisibleSelected, listBookings]);

  const toggleBookingSelection = useCallback((bookingId: string) => {
    setSelectedBookingIds((current) => {
      const next = new Set(current);
      if (next.has(bookingId)) {
        next.delete(bookingId);
      } else {
        next.add(bookingId);
      }
      return next;
    });
  }, []);

  const handleExportCsv = useCallback(() => {
    if (selectedBookings.length === 0) return;
    const csv = buildCsvContent(selectedBookings, includeNotes);
    downloadCsv(csv, `schedule-list-${listFrom || "range"}.csv`);
  }, [buildCsvContent, downloadCsv, includeNotes, listFrom, selectedBookings]);

  const handlePrint = useCallback(() => {
    if (selectedBookings.length === 0) return;
    openPrintView(
      selectedBookings,
      `Schedule List (${listFrom || "range"} → ${listTo || ""})`,
      includeNotes
    );
  }, [includeNotes, listFrom, listTo, openPrintView, selectedBookings]);

  const openQuickCreate = useCallback(
    (day: string, minutes: number) => {
      const start = buildOrgZonedInstant(day, minutes, orgTimezone);
      setQuickCreateStart(formatDateTimeInput(start));
      setQuickCreateDuration(120);
      setDurationTouched(false);
      setQuickCreatePrice("");
      setPriceTouched(false);
      setQuickCreateDeposit("");
      setClientQuery("");
      setClientOptions([]);
      setSelectedClientId("");
      setCreatingClient(false);
      setNewClientName("");
      setNewClientEmail("");
      setNewClientPhone("");
      setAddressOptions([]);
      setSelectedAddressId("");
      setUseNewAddress(false);
      setNewAddressLabel("Primary");
      setNewAddressText("");
      setSelectedServiceTypeId("");
      setSelectedAddonIds(new Set());
      setSelectedWorkerId("");
      setWorkerSuggestions([]);
      setAvailableWorkers([]);
      setQuickCreateError(null);
      setQuickCreateOpen(true);
    },
    [orgTimezone]
  );

  useEffect(() => {
    if (prefillApplied) return;
    if (searchParams.get("quick_create") !== "1") return;
    if (!canCreate) return;
    const leadName = searchParams.get("lead_name") ?? "";
    const leadEmail = searchParams.get("lead_email") ?? "";
    const leadPhone = searchParams.get("lead_phone") ?? "";
    const leadAddress = searchParams.get("lead_address") ?? "";
    const leadPostal = searchParams.get("lead_postal_code") ?? "";
    const targetDay = searchParams.get("date") ?? defaultDate;

    openQuickCreate(targetDay, 9 * 60);
    if (leadName || leadEmail || leadPhone) {
      setCreatingClient(true);
      setNewClientName(leadName);
      setNewClientEmail(leadEmail);
      setNewClientPhone(leadPhone);
    }
    if (leadAddress || leadPostal) {
      setUseNewAddress(true);
      setNewAddressLabel("Lead");
      setNewAddressText(`${leadAddress}${leadPostal ? `, ${leadPostal}` : ""}`.trim());
    }
    setPrefillApplied(true);
  }, [
    canCreate,
    defaultDate,
    openQuickCreate,
    prefillApplied,
    searchParams,
  ]);

  const closeQuickCreate = useCallback(() => {
    setQuickCreateOpen(false);
    setQuickCreateError(null);
  }, []);

  const toggleAddon = useCallback((addonId: number) => {
    setSelectedAddonIds((current) => {
      const next = new Set(current);
      if (next.has(addonId)) {
        next.delete(addonId);
      } else {
        next.add(addonId);
      }
      return next;
    });
  }, []);

  const handleQuickCreate = useCallback(async () => {
    if (!canCreate) return;
    const startDate = parseDateTimeLocal(quickCreateStart);
    if (!startDate) {
      setQuickCreateError("Select a valid start time.");
      return;
    }
    if (!quickCreateDuration || quickCreateDuration <= 0) {
      setQuickCreateError("Duration must be greater than zero.");
      return;
    }
    const priceCents = centsFromInput(quickCreatePrice);
    if (!quickCreatePrice || priceCents <= 0) {
      setQuickCreateError("Enter a price.");
      return;
    }
    if (creatingClient) {
      if (!newClientName || !newClientEmail || !newClientPhone) {
        setQuickCreateError("Enter name, email, and phone for the new client.");
        return;
      }
    } else if (!selectedClientId) {
      setQuickCreateError("Select a client.");
      return;
    }

    if (useNewAddress) {
      if (!newAddressText) {
        setQuickCreateError("Enter an address.");
        return;
      }
    } else if (!selectedAddressId) {
      setQuickCreateError("Select an address.");
      return;
    }

    const payload: Record<string, unknown> = {
      starts_at: startDate.toISOString(),
      duration_minutes: quickCreateDuration,
      price_cents: priceCents,
      deposit_cents: quickCreateDeposit ? centsFromInput(quickCreateDeposit) : null,
      service_type_id: selectedServiceTypeId ? Number(selectedServiceTypeId) : null,
      addon_ids: Array.from(selectedAddonIds),
      assigned_worker_id: selectedWorkerId ? Number(selectedWorkerId) : null,
    };

    if (creatingClient) {
      payload.client = {
        name: newClientName,
        email: newClientEmail,
        phone: newClientPhone,
      };
    } else {
      payload.client_id = selectedClientId;
    }

    if (useNewAddress) {
      payload.address_text = newAddressText;
      payload.address_label = newAddressLabel || "Primary";
    } else {
      payload.address_id = Number(selectedAddressId);
    }

    setQuickCreateError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/schedule/quick-create`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const message = payload?.detail || response.statusText || "Create failed";
        throw new Error(message);
      }
      closeQuickCreate();
      refreshSchedule();
      showToast("Booking created", "success");
    } catch (fetchError) {
      setQuickCreateError(fetchError instanceof Error ? fetchError.message : "Create failed");
    }
  }, [
    authHeaders,
    canCreate,
    closeQuickCreate,
    creatingClient,
    newAddressLabel,
    newAddressText,
    newClientEmail,
    newClientName,
    newClientPhone,
    quickCreateDeposit,
    quickCreateDuration,
    quickCreatePrice,
    quickCreateStart,
    refreshSchedule,
    selectedAddonIds,
    selectedAddressId,
    selectedClientId,
    selectedServiceTypeId,
    selectedWorkerId,
    showToast,
    useNewAddress,
  ]);

  const handleSlotClick = useCallback(
    (event: MouseEvent<HTMLDivElement>, day: string) => {
      if (!canCreate) return;
      const target = event.target as HTMLElement;
      if (target.closest(".schedule-booking")) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const offsetY = Math.max(0, event.clientY - rect.top);
      const rawMinutes = Math.round(offsetY / SLOT_HEIGHT) * SLOT_MINUTES;
      const minutesFromStart = Math.min(Math.max(rawMinutes, 0), dayMinutes);
      const minutes = START_HOUR * 60 + minutesFromStart;
      openQuickCreate(day, minutes);
    },
    [canCreate, dayMinutes, openQuickCreate]
  );

  if (visibilityReady && !scheduleVisible) {
    return (
      <div className="schedule-page">
        <AdminNav links={navLinks} activeKey="schedule" />
        <section className="card">
          <div className="card-body">
            <h1>Schedule</h1>
            <p className="muted">Schedule module access is disabled for your role.</p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="schedule-page" data-testid="schedule-page">
      <AdminNav links={navLinks} activeKey="schedule" />
      <header className="schedule-header">
        <div>
          <h1>{viewTitle}</h1>
          <p className="muted">
            {isListLikeView ? viewSubtitle : `${viewSubtitle} (${orgTimezone}).`}
          </p>
        </div>
        {toast ? (
          <div className={`schedule-toast ${toast.kind}`} data-testid="schedule-toast">{toast.message}</div>
        ) : null}
      </header>

      <section className="card" data-testid="schedule-auth-section">
        <div className="card-body">
          <div className="schedule-auth">
            <div className="schedule-auth-fields">
              <input
                className="input"
                type="text"
                data-testid="schedule-username-input"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin"
              />
              <input
                className="input"
                type="password"
                data-testid="schedule-password-input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="password"
              />
            </div>
            <div className="schedule-auth-actions">
              <button
                className="btn btn-primary"
                type="button"
                data-testid="schedule-save-btn"
                onClick={() => {
                  if (username && password) {
                    window.localStorage.setItem(ADMIN_STORAGE_USERNAME_KEY, username);
                    window.localStorage.setItem(ADMIN_STORAGE_PASSWORD_KEY, password);
                    void loadProfile();
                    void loadFeatureConfig();
                    void loadUiPrefs();
                    void loadOrgSettings();
                  }
                }}
              >
                Save Credentials
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                data-testid="schedule-clear-btn"
                onClick={() => {
                  setUsername("");
                  setPassword("");
                  window.localStorage.removeItem(ADMIN_STORAGE_USERNAME_KEY);
                  window.localStorage.removeItem(ADMIN_STORAGE_PASSWORD_KEY);
                  setProfile(null);
                  setSchedule(null);
                }}
              >
                Clear
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-body">
          <div className="schedule-controls">
            <div className="schedule-view-tabs" role="tablist" data-testid="schedule-view-tabs">
              {[
                { key: "day", label: "Day" },
                { key: "week", label: "Week" },
                { key: "timeline", label: "Timeline" },
                { key: "teams", label: "Teams" },
                { key: "month", label: "Month" },
                { key: "list", label: "List" },
              ].map((view) => (
                <button
                  key={view.key}
                  className={`schedule-view-tab${viewMode === view.key ? " active" : ""}`}
                  type="button"
                  role="tab"
                  aria-selected={viewMode === view.key}
                  onClick={() => handleViewChange(view.key)}
                >
                  {view.label}
                </button>
              ))}
            </div>
            {showWeekControls ? (
              <div className="schedule-week-controls">
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={() => updateQuery({ date: addDaysYMD(selectedDate, -navigationStep, orgTimezone) })}
                >
                  Previous
                </button>
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={() => updateQuery({ date: defaultDate })}
                >
                  Today
                </button>
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={() => updateQuery({ date: addDaysYMD(selectedDate, navigationStep, orgTimezone) })}
                >
                  Next
                </button>
                <input
                  className="input"
                  type="date"
                  value={selectedDate}
                  onChange={(event) => updateQuery({ date: event.target.value })}
                />
              </div>
            ) : (
              <div className="schedule-list-controls">
                <label className="stack">
                  <span className="muted">From</span>
                  <input
                    className="input"
                    type="date"
                    value={listFrom}
                    onChange={(event) => updateQuery({ from: event.target.value, page: "1" })}
                  />
                </label>
                <label className="stack">
                  <span className="muted">To</span>
                  <input
                    className="input"
                    type="date"
                    value={listTo}
                    onChange={(event) => updateQuery({ to: event.target.value, page: "1" })}
                  />
                </label>
                <label className="stack schedule-search">
                  <span className="muted">Search</span>
                  <input
                    className="input"
                    value={searchQuery}
                    onChange={(event) => updateQuery({ q: event.target.value, page: "1" })}
                    placeholder="Booking id, client, address..."
                  />
                </label>
              </div>
            )}
            <div className="schedule-filters">
              <label className="stack">
                <span className="muted">Team</span>
                <select
                  className="input"
                  value={teamFilter}
                  onChange={(event) =>
                    updateQuery({
                      team_id: event.target.value,
                      page: isListLikeView ? "1" : "",
                    })
                  }
                >
                  <option value="">All teams</option>
                  {teamOptions.map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack">
                <span className="muted">Worker</span>
                <select
                  className="input"
                  value={workerFilter}
                  onChange={(event) =>
                    updateQuery({
                      worker_id: event.target.value,
                      page: isListLikeView ? "1" : "",
                    })
                  }
                >
                  <option value="">All workers</option>
                  {workerOptions.map((worker) => (
                    <option key={worker.id} value={worker.id}>
                      {worker.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack">
                <span className="muted">Status</span>
                <select
                  className="input"
                  value={statusFilter}
                  onChange={(event) =>
                    updateQuery({
                      status: event.target.value,
                      page: isListLikeView ? "1" : "",
                    })
                  }
                >
                  <option value="">All statuses</option>
                  {statusOptions.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {showCalendar && !canAssign ? (
            <p className="muted schedule-readonly">Read-only role: drag & drop disabled.</p>
          ) : null}
          {error ? <p className="muted schedule-error">{error}</p> : null}
          {loading ? <p className="muted">Loading schedule…</p> : null}
        </div>
      </section>

      <section className="card schedule-export">
        <div className="card-body">
          <div className="schedule-export-header">
            <div>
              <h2>Export & Print</h2>
              <p className="muted">
                Export the current schedule range with booking details and worker assignments.
              </p>
            </div>
            <div className="schedule-export-actions">
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => void handleRangeExportCsv()}
                disabled={exportLoading}
              >
                {exportLoading ? "Exporting…" : "Export CSV"}
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => void handleRangePrint()}
                disabled={exportLoading}
              >
                {exportLoading ? "Preparing…" : "Print"}
              </button>
            </div>
          </div>
          <div className="schedule-export-controls">
            <label className="stack">
              <span className="muted">Range</span>
              <select
                className="input"
                value={exportRange}
                onChange={(event) =>
                  setExportRange(event.target.value as "week" | "month" | "custom")
                }
              >
                <option value="week">Current week</option>
                <option value="month">Current month</option>
                <option value="custom">Custom range</option>
              </select>
            </label>
            {exportRange === "custom" ? (
              <>
                <label className="stack">
                  <span className="muted">From</span>
                  <input
                    className="input"
                    type="date"
                    value={exportFrom}
                    onChange={(event) => setExportFrom(event.target.value)}
                  />
                </label>
                <label className="stack">
                  <span className="muted">To</span>
                  <input
                    className="input"
                    type="date"
                    value={exportTo}
                    onChange={(event) => setExportTo(event.target.value)}
                  />
                </label>
              </>
            ) : (
              <div className="schedule-export-summary">
                <span className="muted">Range summary</span>
                <strong>{exportRangeLabel}</strong>
              </div>
            )}
            <label className="schedule-toggle schedule-export-notes">
              <input
                type="checkbox"
                checked={includeNotes}
                onChange={(event) => setIncludeNotes(event.target.checked)}
              />
              <span>Include notes (client/address)</span>
            </label>
          </div>
          <p className="muted schedule-export-filters">{exportFiltersLabel}</p>
        </div>
      </section>

      {optimizationVisible ? (
        <section className="card schedule-optimization">
          <div className="card-body">
            <div className="schedule-optimization-header">
              <div>
                <h2>Optimization</h2>
                <p className="muted">
                  Deterministic, read-only scheduling suggestions for the selected range.
                </p>
              </div>
            </div>
            {optimizationLoading ? <p className="muted">Loading suggestions…</p> : null}
            {optimizationError ? (
              <p className="muted schedule-error">{optimizationError}</p>
            ) : null}
            {optimizationSuggestions.length ? (
              <div className="schedule-optimization-list">
                {optimizationSuggestions.map((suggestion) => {
                  const expanded = expandedSuggestionIds.has(suggestion.id);
                  const workerCount = suggestion.apply_payload.candidate_worker_ids.length;
                  const canApply = canAssign && workerCount > 0;
                  return (
                    <div key={suggestion.id} className="schedule-optimization-item">
                      <div className="schedule-optimization-main">
                        <div>
                          <div className="schedule-optimization-title">{suggestion.title}</div>
                          <div className="muted">{suggestion.rationale}</div>
                          {suggestion.estimated_impact ? (
                            <div className="muted">
                              Impact: {suggestion.estimated_impact}
                            </div>
                          ) : null}
                        </div>
                        <div className="schedule-optimization-actions">
                          <span
                            className={`schedule-optimization-severity ${suggestion.severity}`}
                          >
                            {suggestion.severity}
                          </span>
                          <button
                            className="btn btn-primary"
                            type="button"
                            onClick={() => openApplyDialog(suggestion)}
                            disabled={!canApply}
                            title={!canApply ? "No available workers to apply." : "Apply suggestion"}
                          >
                            Apply
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => toggleSuggestionDetails(suggestion.id)}
                          >
                            {expanded ? "Hide details" : "View details"}
                          </button>
                        </div>
                      </div>
                      {expanded ? (
                        <div className="schedule-optimization-details">
                          <div className="schedule-optimization-detail-row">
                            <span className="muted">Suggested workers</span>
                            <span>
                              {workerCount
                                ? `${workerCount} candidate${workerCount === 1 ? "" : "s"}`
                                : "None available"}
                            </span>
                          </div>
                          <div className="schedule-optimization-detail-row">
                            <span className="muted">Apply payload</span>
                            <pre className="schedule-optimization-payload">
                              {JSON.stringify(suggestion.apply_payload, null, 2)}
                            </pre>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : !optimizationLoading && !optimizationError ? (
              <p className="muted schedule-empty">No optimization suggestions in this range.</p>
            ) : null}
          </div>
        </section>
      ) : null}

      {isListLikeView ? (
        <section className="card schedule-list">
          <div className="card-body">
            <div className="schedule-list-toolbar">
              <div className="schedule-bulk-actions">
                <label className="schedule-checkbox">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleSelectAll}
                  />
                  <span>Select page</span>
                </label>
                <span className="muted">
                  {selectedBookingIds.size > 0
                    ? `${selectedBookingIds.size} selected`
                    : `${listBookings.length} visible`}
                </span>
              </div>
              <div className="schedule-list-actions">
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={handleExportCsv}
                  disabled={selectedBookings.length === 0}
                >
                  Export CSV
                </button>
                <button
                  className="btn btn-secondary"
                  type="button"
                  onClick={handlePrint}
                  disabled={selectedBookings.length === 0}
                >
                  Print
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled
                  title="Bulk reminders are not available for schedule yet."
                >
                  Remind
                </button>
              </div>
              <div className="schedule-pagination">
                <span className="muted">
                  {totalBookings === 0
                    ? "No bookings"
                    : `${currentRangeStart}-${currentRangeEnd} of ${totalBookings}`}
                </span>
                <div className="schedule-pagination-actions">
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={currentPage <= 1}
                    onClick={() => updateQuery({ page: String(currentPage - 1) })}
                  >
                    Previous
                  </button>
                  <span className="muted">
                    Page {currentPage} of {totalPages}
                  </span>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={currentPage >= totalPages}
                    onClick={() => updateQuery({ page: String(currentPage + 1) })}
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>

            {listBookings.length === 0 ? (
              <p className="muted schedule-empty">No bookings found for this range.</p>
            ) : (
              <div className="schedule-list-table">
                <table>
                  <thead>
                    <tr>
                      <th />
                      <th>Date/Time</th>
                      <th>Booking ID</th>
                      <th>Worker/Team</th>
                      <th>Client</th>
                      <th>Address</th>
                      <th>Status</th>
                      <th>Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listBookings.map((booking) => (
                      <tr key={booking.booking_id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedBookingIds.has(booking.booking_id)}
                            onChange={() => toggleBookingSelection(booking.booking_id)}
                          />
                        </td>
                        <td>{formatDateTimeLabel(booking.starts_at, orgTimezone)}</td>
                        <td>{booking.booking_id}</td>
                        <td>
                          <div>{booking.worker_name ?? "Unassigned"}</div>
                          <div className="muted">{booking.team_name ?? "—"}</div>
                        </td>
                        <td>{booking.client_label ?? "—"}</td>
                        <td>{booking.address ?? "—"}</td>
                        <td>{booking.status}</td>
                        <td>{formatCurrencyFromCents(booking.price_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      ) : null}

      {isTimelineView ? (
        <section className="card schedule-timeline">
          <div className="card-body">
            {timelineLoading ? <p className="muted">Loading worker timeline…</p> : null}
            {timelineError ? <p className="muted schedule-error">{timelineError}</p> : null}
            {workerTimeline && workerTimeline.workers.length > 0 ? (
              <div className="schedule-timeline-table-wrapper">
                <table className="schedule-timeline-table">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      {timelineDays.map((day) => (
                        <th key={day}>{formatDayLabel(day, orgTimezone)}</th>
                      ))}
                      <th>Utilization</th>
                    </tr>
                  </thead>
                  <tbody>
                    {workerTimeline.workers.map((worker) => {
                      const dayMap = new Map(
                        worker.days.map((entry) => [entry.date, entry] as const)
                      );
                      const utilization = timelineAvailableMinutes
                        ? Math.round((worker.totals.booked_minutes / timelineAvailableMinutes) * 100)
                        : 0;
                      return (
                        <tr key={worker.worker_id}>
                          <td className="schedule-timeline-worker">
                            <div>{worker.name}</div>
                            <div className="muted">{worker.team_name ?? "—"}</div>
                          </td>
                          {timelineDays.map((day) => {
                            const entry = dayMap.get(day) ?? {
                              booked_minutes: 0,
                              booking_count: 0,
                              revenue_cents: 0,
                              booking_ids: [],
                            };
                            const revenueLabel = entry.revenue_cents
                              ? formatCurrencyFromCents(entry.revenue_cents)
                              : "—";
                            return (
                              <td key={`${worker.worker_id}-${day}`}>
                                <button
                                  className="schedule-timeline-link"
                                  type="button"
                                  onClick={() =>
                                    updateQuery({
                                      view: "day",
                                      date: day,
                                      worker_id: String(worker.worker_id),
                                      from: "",
                                      to: "",
                                      page: "",
                                      q: "",
                                    })
                                  }
                                >
                                  <div>{formatHoursFromMinutes(entry.booked_minutes)}</div>
                                  <div className="muted">
                                    {formatBookingCount(entry.booking_count)}
                                  </div>
                                  <div className="muted">{revenueLabel}</div>
                                </button>
                              </td>
                            );
                          })}
                          <td>
                            <div>{formatHoursFromMinutes(worker.totals.booked_minutes)}</div>
                            <div className="muted">
                              {timelineAvailableMinutes ? `${utilization}%` : "—"}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="schedule-timeline-total-row">
                      <td>
                        <strong>Totals</strong>
                      </td>
                      {timelineDays.map((day) => {
                        const totals = timelineTotalsByDay.get(day) ?? {
                          booked_minutes: 0,
                          booking_count: 0,
                          revenue_cents: 0,
                        };
                        const revenueLabel = totals.revenue_cents
                          ? formatCurrencyFromCents(totals.revenue_cents)
                          : "—";
                        return (
                          <td key={`total-${day}`}>
                            <div>{formatHoursFromMinutes(totals.booked_minutes)}</div>
                            <div className="muted">
                              {formatBookingCount(totals.booking_count)}
                            </div>
                            <div className="muted">{revenueLabel}</div>
                          </td>
                        );
                      })}
                      <td>
                        <div>{formatHoursFromMinutes(workerTimeline.totals.booked_minutes)}</div>
                        <div className="muted">
                          {timelineAvailableMinutes && workerTimeline.workers.length
                            ? `${Math.round(
                                (workerTimeline.totals.booked_minutes /
                                  (timelineAvailableMinutes * workerTimeline.workers.length)) *
                                  100
                              )}%`
                            : "—"}
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted schedule-empty">No workers found for this range.</p>
            )}
          </div>
        </section>
      ) : null}

      {isTeamView ? (
        <section className="card schedule-team-calendar">
          <div className="card-body">
            {teamCalendarLoading ? <p className="muted">Loading team calendar…</p> : null}
            {teamCalendarError ? <p className="muted schedule-error">{teamCalendarError}</p> : null}
            {teamCalendar && teamCalendar.teams.length > 0 ? (
              <div className="schedule-team-calendar-grid">
                {teamCalendar.teams.map((team) => {
                  const dayMap = new Map(team.days.map((entry) => [entry.date, entry] as const));
                  return (
                    <div key={team.team_id} className="schedule-team-card">
                      <div className="schedule-team-card-header">
                        <div>
                          <h3>{team.name}</h3>
                          <p className="muted">Team {team.team_id}</p>
                        </div>
                        <a
                          className="btn btn-ghost"
                          href={`/admin/schedule?view=week&team_id=${team.team_id}&date=${selectedDate}`}
                        >
                          Open schedule
                        </a>
                      </div>
                      <div className="schedule-team-days">
                        {teamCalendarDays.map((day) => {
                          const entry = dayMap.get(day) ?? {
                            date: day,
                            bookings: 0,
                            revenue: 0,
                            workers_used: 0,
                          };
                          const revenueLabel = entry.revenue
                            ? formatCurrencyFromCents(entry.revenue)
                            : "—";
                          return (
                            <button
                              key={`${team.team_id}-${day}`}
                              className="schedule-team-day"
                              type="button"
                              onClick={() =>
                                updateQuery({
                                  view: "day",
                                  date: day,
                                  team_id: String(team.team_id),
                                  from: "",
                                  to: "",
                                  page: "",
                                  q: "",
                                })
                              }
                            >
                              <div className="schedule-team-day-label">
                                {formatDayLabel(day, orgTimezone)}
                              </div>
                              <div>{formatBookingCount(entry.bookings)}</div>
                              <div className="muted">
                                {entry.workers_used
                                  ? `${entry.workers_used} worker${
                                      entry.workers_used === 1 ? "" : "s"
                                    }`
                                  : "—"}
                              </div>
                              <div className="muted">{revenueLabel}</div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="muted schedule-empty">No teams found for this range.</p>
            )}
          </div>
        </section>
      ) : null}

      {showCalendar ? (
        <section className={`schedule-grid${isDayView ? " day" : ""}`}>
          <div className="schedule-time-column">
            <div className="schedule-day-header">Time</div>
            <div className="schedule-time-body" style={{ height: gridHeight }}>
              {timeSlots.map((hour, index) => (
                <div
                  key={hour}
                  className="schedule-time-slot"
                  style={{ height: SLOT_HEIGHT * (index === timeSlots.length - 1 ? 1 : 2) }}
                >
                  {formatTimeLabel(hour)}
                </div>
              ))}
            </div>
          </div>

          {visibleDays.map((day) => {
            const bookings = bookingsByDay.get(day) ?? [];
            return (
              <div
                key={day}
                className="schedule-day-column"
                onDragOver={(event) => {
                  if (!canAssign) return;
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                }}
                onDrop={(event) => handleDrop(event, day)}
              >
                <div className="schedule-day-header">{formatDayLabel(day, orgTimezone)}</div>
                <div
                  className="schedule-day-body"
                  style={{ height: gridHeight }}
                  onClick={(event) => handleSlotClick(event, day)}
                >
                  {bookings.map((booking) => {
                    const bookingStartMinutes = minutesFromTime(booking.starts_at, orgTimezone);
                    const bookingEndMinutes = minutesFromTime(booking.ends_at, orgTimezone);
                    const warnings = bookingWarnings.get(booking.booking_id) ?? [];
                    const top =
                      ((bookingStartMinutes - START_HOUR * 60) / SLOT_MINUTES) * SLOT_HEIGHT;
                    const height =
                      ((bookingEndMinutes - bookingStartMinutes) / SLOT_MINUTES) * SLOT_HEIGHT;
                    const clampedTop = Math.max(0, top);
                    const clampedHeight = Math.max(
                      SLOT_HEIGHT,
                      Math.min(height, gridHeight - clampedTop)
                    );
                    return (
                      <div
                        key={booking.booking_id}
                        className={`schedule-booking${
                          draggingBookingId === booking.booking_id ? " dragging" : ""
                        }`}
                        style={{
                          top: clampedTop,
                          height: clampedHeight,
                        }}
                        draggable={canAssign}
                        onDragStart={(event) => {
                          if (!canAssign) return;
                          setDraggingBookingId(booking.booking_id);
                          event.dataTransfer.setData("text/plain", booking.booking_id);
                          event.dataTransfer.effectAllowed = "move";
                        }}
                        onDragEnd={() => setDraggingBookingId(null)}
                      >
                        <div className="schedule-booking-title">
                          {booking.client_label ?? "Booking"}
                        </div>
                        <div className="schedule-booking-subtitle">
                          {booking.service_label ?? booking.status}
                        </div>
                        <div className="schedule-booking-meta">
                          {formatTimeRange(booking.starts_at, booking.ends_at, orgTimezone)}
                        </div>
                        <div className="schedule-booking-meta">
                          {booking.worker_name ? `Worker: ${booking.worker_name}` : "Unassigned"}
                        </div>
                        <div className="schedule-booking-meta">
                          {formatCurrencyFromCents(booking.price_cents)}
                        </div>
                        {warnings.map((warning) => (
                          <div className="schedule-booking-warning" key={warning}>
                            ⚠️ {warning}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </section>
      ) : null}

      {applySuggestion ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeApplyDialog} />
          <div className="schedule-modal-panel">
            <header className="schedule-modal-header">
              <div>
                <h2>Apply optimization</h2>
                <p className="muted">Confirm the assignment before applying.</p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeApplyDialog}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body">
              {applyError ? <div className="inline-alert error">{applyError}</div> : null}
              <div className="stack">
                <div className="schedule-optimization-detail-row">
                  <span className="muted">Suggestion</span>
                  <span>{applySuggestion.title}</span>
                </div>
                <div className="schedule-optimization-detail-row">
                  <span className="muted">Booking</span>
                  <span>{applySuggestion.apply_payload.booking_id}</span>
                </div>
                <div className="schedule-optimization-detail-row">
                  <span className="muted">Candidate workers</span>
                  <span>
                    {applyCandidateCount
                      ? `${applyCandidateCount} available candidate${applyCandidateCount === 1 ? "" : "s"}`
                      : "None available"}
                  </span>
                </div>
                <p className="muted">
                  Applying will assign the first available candidate worker and re-check conflicts
                  before saving.
                </p>
              </div>
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeApplyDialog}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => void handleApplySuggestion()}
                disabled={applySubmitting || applyCandidateCount === 0}
              >
                {applySubmitting ? "Applying…" : "Apply suggestion"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}

      {quickCreateOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeQuickCreate} />
          <div className="schedule-modal-panel">
            <header className="schedule-modal-header">
              <div>
                <h2>Quick create booking</h2>
                <p className="muted">Click a slot to prefill the time and create a booking fast.</p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeQuickCreate}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body">
              {quickCreateError ? <div className="inline-alert error">{quickCreateError}</div> : null}
              <div className="schedule-modal-grid">
                <div className="schedule-modal-section">
                  <h3>Client</h3>
                  <label className="schedule-toggle">
                    <input
                      type="checkbox"
                      checked={creatingClient}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setCreatingClient(checked);
                        setSelectedClientId("");
                        setClientQuery("");
                        setClientOptions([]);
                        setAddressOptions([]);
                        setSelectedAddressId("");
                        setUseNewAddress(checked);
                      }}
                    />
                    <span>Create new client</span>
                  </label>
                  {creatingClient ? (
                    <div className="stack">
                      <label className="stack">
                        <span className="muted">Name</span>
                        <input
                          className="input"
                          value={newClientName}
                          onChange={(event) => setNewClientName(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span className="muted">Email</span>
                        <input
                          className="input"
                          type="email"
                          value={newClientEmail}
                          onChange={(event) => setNewClientEmail(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span className="muted">Phone</span>
                        <input
                          className="input"
                          value={newClientPhone}
                          onChange={(event) => setNewClientPhone(event.target.value)}
                        />
                      </label>
                    </div>
                  ) : (
                    <div className="stack">
                      <label className="stack">
                        <span className="muted">Search</span>
                        <input
                          className="input"
                          placeholder="Search clients by name, email, phone"
                          value={clientQuery}
                          onChange={(event) => setClientQuery(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span className="muted">Select client</span>
                        <select
                          className="input"
                          value={selectedClientId}
                          onChange={(event) => setSelectedClientId(event.target.value)}
                        >
                          <option value="">Select client</option>
                          {clientOptions.map((client) => (
                            <option key={client.client_id} value={client.client_id}>
                              {client.name || client.email}
                            </option>
                          ))}
                        </select>
                      </label>
                      {clientOptions.length === 0 && clientQuery ? (
                        <span className="muted">No matching clients.</span>
                      ) : null}
                    </div>
                  )}
                </div>

                <div className="schedule-modal-section">
                  <h3>Address</h3>
                  <label className="schedule-toggle">
                    <input
                      type="checkbox"
                      checked={useNewAddress}
                      onChange={(event) => setUseNewAddress(event.target.checked)}
                    />
                    <span>Enter new address</span>
                  </label>
                  {useNewAddress ? (
                    <div className="stack">
                      <label className="stack">
                        <span className="muted">Label</span>
                        <input
                          className="input"
                          value={newAddressLabel}
                          onChange={(event) => setNewAddressLabel(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span className="muted">Address</span>
                        <input
                          className="input"
                          value={newAddressText}
                          onChange={(event) => setNewAddressText(event.target.value)}
                        />
                      </label>
                    </div>
                  ) : (
                    <label className="stack">
                      <span className="muted">Saved address</span>
                      <select
                        className="input"
                        value={selectedAddressId}
                        onChange={(event) => setSelectedAddressId(event.target.value)}
                      >
                        <option value="">Select address</option>
                        {addressOptions.map((address) => (
                          <option key={address.address_id} value={address.address_id}>
                            {address.label} · {address.address_text}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>

                <div className="schedule-modal-section">
                  <h3>Service</h3>
                  <label className="stack">
                    <span className="muted">Service type</span>
                    <select
                      className="input"
                      value={selectedServiceTypeId}
                      onChange={(event) => setSelectedServiceTypeId(event.target.value)}
                    >
                      <option value="">Select service</option>
                      {serviceTypes.map((service) => (
                        <option key={service.service_type_id} value={service.service_type_id}>
                          {service.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {addonOptions.length ? (
                    <div className="schedule-addon-list">
                      <span className="muted">Add-ons</span>
                      {addonOptions.map((addon) => (
                        <label key={addon.addon_id} className="schedule-addon-item">
                          <input
                            type="checkbox"
                            checked={selectedAddonIds.has(addon.addon_id)}
                            onChange={() => toggleAddon(addon.addon_id)}
                          />
                          <span>
                            {addon.name} · {formatCurrencyFromCents(addon.price_cents)}
                          </span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <span className="muted">No add-ons configured.</span>
                  )}
                  {selectedServiceType ? (
                    <span className="muted">Default duration: {selectedServiceType.default_duration_minutes} min</span>
                  ) : null}
                </div>

                <div className="schedule-modal-section">
                  <h3>Timing</h3>
                  <label className="stack">
                    <span className="muted">Start</span>
                    <input
                      className="input"
                      type="datetime-local"
                      value={quickCreateStart}
                      onChange={(event) => setQuickCreateStart(event.target.value)}
                    />
                  </label>
                  <label className="stack">
                    <span className="muted">Duration (minutes)</span>
                    <input
                      className="input"
                      type="number"
                      min={30}
                      step={15}
                      value={quickCreateDuration}
                      onChange={(event) => {
                        setDurationTouched(true);
                        setQuickCreateDuration(Number(event.target.value));
                      }}
                    />
                  </label>
                </div>

                <div className="schedule-modal-section">
                  <h3>Worker</h3>
                  {workerSuggestions.length ? (
                    <div className="schedule-suggestions">
                      {workerSuggestions.map((worker) => (
                        <button
                          key={worker.worker_id}
                          type="button"
                          className={`schedule-suggestion${selectedWorkerId === String(worker.worker_id) ? " active" : ""}`}
                          onClick={() => setSelectedWorkerId(String(worker.worker_id))}
                        >
                          <strong>{worker.name}</strong>
                          <span className="muted">{worker.team_name}</span>
                          <span className="muted">{worker.reasons.join(", ")}</span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <span className="muted">No available workers for this slot.</span>
                  )}
                  <label className="stack">
                    <span className="muted">Assign manually</span>
                    <select
                      className="input"
                      value={selectedWorkerId}
                      onChange={(event) => setSelectedWorkerId(event.target.value)}
                    >
                      <option value="">Unassigned</option>
                      {availableWorkers.map((worker) => (
                        <option key={worker.worker_id} value={worker.worker_id}>
                          {worker.name} · {worker.team_name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="schedule-modal-section">
                  <h3>Pricing</h3>
                  <label className="stack">
                    <span className="muted">Price (CAD)</span>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step={0.01}
                      value={quickCreatePrice}
                      onChange={(event) => {
                        setPriceTouched(true);
                        setQuickCreatePrice(event.target.value);
                      }}
                    />
                  </label>
                  <label className="stack">
                    <span className="muted">Deposit (CAD)</span>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step={0.01}
                      value={quickCreateDeposit}
                      onChange={(event) => setQuickCreateDeposit(event.target.value)}
                    />
                  </label>
                </div>
              </div>
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeQuickCreate}>
                Cancel
              </button>
              <button className="btn btn-primary" type="button" onClick={() => void handleQuickCreate()}>
                Create booking
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
