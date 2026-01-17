"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

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

type TrainingCourse = {
  course_id: string;
  title: string;
  description?: string | null;
  duration_minutes?: number | null;
  active: boolean;
  format?: "video" | "doc" | "in_person" | "mixed" | null;
  created_at: string;
};

type TrainingCourseListResponse = {
  items: TrainingCourse[];
  total: number;
};

type CourseDraft = {
  title: string;
  description: string;
  duration_minutes: string;
  active: boolean;
  format: "" | "video" | "doc" | "in_person" | "mixed";
};

const EMPTY_DRAFT: CourseDraft = {
  title: "",
  description: "",
  duration_minutes: "",
  active: true,
  format: "",
};

function parseDuration(value: string) {
  if (!value.trim()) return undefined;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return undefined;
  return numeric;
}

function formatMinutes(value?: number | null) {
  if (!value && value !== 0) return "—";
  return `${value} min`;
}

export default function TrainingCoursesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [courses, setCourses] = useState<TrainingCourse[]>([]);
  const [includeInactive, setIncludeInactive] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<CourseDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [editingCourse, setEditingCourse] = useState<TrainingCourse | null>(null);
  const [saving, setSaving] = useState(false);

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

  const loadCourses = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/training/courses?include_inactive=${includeInactive}`,
        { headers: authHeaders }
      );
      if (!response.ok) throw new Error(`Failed (${response.status})`);
      const data = (await response.json()) as TrainingCourseListResponse;
      setCourses(data.items);
    } catch (err) {
      console.error("Failed to load courses", err);
      setError("Unable to load training courses.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, includeInactive, password, username]);

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
    loadCourses();
  }, [loadCourses, pageVisible]);

  const resetDraft = useCallback(() => {
    setDraft(EMPTY_DRAFT);
    setDraftErrors([]);
    setEditingCourse(null);
  }, []);

  const openCreate = useCallback(() => {
    resetDraft();
    setModalOpen(true);
  }, [resetDraft]);

  const openEdit = useCallback((course: TrainingCourse) => {
    setDraft({
      title: course.title,
      description: course.description ?? "",
      duration_minutes: course.duration_minutes ? String(course.duration_minutes) : "",
      active: course.active,
      format: course.format ?? "",
    });
    setDraftErrors([]);
    setEditingCourse(course);
    setModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSaving(false);
  }, []);

  const handleSave = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!username || !password) return;
      const errors: string[] = [];
      if (!draft.title.trim()) errors.push("Course title is required.");
      if (errors.length) {
        setDraftErrors(errors);
        return;
      }
      setSaving(true);
      setDraftErrors([]);
      setStatusMessage(null);
      try {
        const payload = {
          title: draft.title.trim(),
          description: draft.description.trim() ? draft.description.trim() : null,
          duration_minutes: parseDuration(draft.duration_minutes),
          active: draft.active,
          format: draft.format ? draft.format : null,
        };
        const response = await fetch(
          editingCourse
            ? `${API_BASE}/v1/admin/training/courses/${editingCourse.course_id}`
            : `${API_BASE}/v1/admin/training/courses`,
          {
            method: editingCourse ? "PATCH" : "POST",
            headers: { ...authHeaders, "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        );
        if (!response.ok) throw new Error(`Failed (${response.status})`);
        setStatusMessage(editingCourse ? "Course updated." : "Course created.");
        setModalOpen(false);
        resetDraft();
        await loadCourses();
      } catch (err) {
        console.error("Failed to save course", err);
        setDraftErrors(["Unable to save course."]);
      } finally {
        setSaving(false);
      }
    },
    [authHeaders, draft, editingCourse, loadCourses, password, resetDraft, username]
  );

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="training" />
        <div className="card">
          <div className="card-body">
            <p className="muted">Training module is disabled for your account.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="training" />
      <div className="card">
        <div className="card-header">
          <div>
            <h1>Training courses</h1>
            <p className="muted">Manage courses and assign workers to required trainings.</p>
          </div>
          {canManage ? (
            <button className="btn btn-primary" type="button" onClick={openCreate}>
              Create course
            </button>
          ) : null}
        </div>
        <div className="card-body">
          {statusMessage ? <div className="success">{statusMessage}</div> : null}
          {error ? <div className="error">{error}</div> : null}
          <label className="stack">
            <span>Include inactive courses</span>
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
            />
          </label>
          {loading ? (
            <p className="muted">Loading courses...</p>
          ) : courses.length ? (
            <table className="table-like">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Format</th>
                  <th>Duration</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {courses.map((course) => (
                  <tr key={course.course_id}>
                    <td>
                      <div>{course.title}</div>
                      <div className="muted">{course.description ?? "No description"}</div>
                    </td>
                    <td>{course.format ?? "—"}</td>
                    <td>{formatMinutes(course.duration_minutes)}</td>
                    <td>
                      <span className={`status-badge ${course.active ? "ok" : "due"}`}>
                        {course.active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td>
                      <Link className="btn btn-ghost" href={`/admin/training/courses/${course.course_id}`}>
                        View
                      </Link>
                      {canManage ? (
                        <button className="btn btn-secondary" type="button" onClick={() => openEdit(course)}>
                          Edit
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No training courses yet.</p>
          )}
        </div>
      </div>
      {modalOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "640px" }}>
            <header className="schedule-modal-header">
              <div>
                <strong>{editingCourse ? "Edit course" : "Create course"}</strong>
                <div className="muted">Provide the course details to publish assignments.</div>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body" style={{ display: "grid", gap: "16px" }}>
              {draftErrors.length ? (
                <div className="error">{draftErrors.map((err) => err).join(" ")}</div>
              ) : null}
              <form className="stack" onSubmit={handleSave}>
                <div className="schedule-modal-grid">
                  <div className="schedule-modal-section">
                    <label className="stack">
                      <span>Title</span>
                      <input
                        value={draft.title}
                        onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))}
                      />
                    </label>
                    <label className="stack">
                      <span>Description</span>
                      <textarea
                        rows={4}
                        value={draft.description}
                        onChange={(event) => setDraft((prev) => ({ ...prev, description: event.target.value }))}
                      />
                    </label>
                  </div>
                  <div className="schedule-modal-section">
                    <label className="stack">
                      <span>Duration (minutes)</span>
                      <input
                        type="number"
                        min="0"
                        value={draft.duration_minutes}
                        onChange={(event) => setDraft((prev) => ({ ...prev, duration_minutes: event.target.value }))}
                      />
                    </label>
                    <label className="stack">
                      <span>Format</span>
                      <select
                        value={draft.format}
                        onChange={(event) =>
                          setDraft((prev) => ({
                            ...prev,
                            format: event.target.value as CourseDraft["format"],
                          }))
                        }
                      >
                        <option value="">Select format</option>
                        <option value="video">Video</option>
                        <option value="doc">Document</option>
                        <option value="in_person">In person</option>
                        <option value="mixed">Mixed</option>
                      </select>
                    </label>
                    <label className="stack">
                      <span>Course is active</span>
                      <input
                        type="checkbox"
                        checked={draft.active}
                        onChange={(event) => setDraft((prev) => ({ ...prev, active: event.target.checked }))}
                      />
                    </label>
                  </div>
                </div>
                <div className="admin-actions">
                  <button className="btn btn-primary" type="submit" disabled={saving}>
                    {saving ? "Saving..." : editingCourse ? "Save changes" : "Create course"}
                  </button>
                  <button className="btn btn-ghost" type="button" onClick={closeModal}>
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
