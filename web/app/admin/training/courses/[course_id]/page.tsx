"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import AdminNav from "../../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../../../lib/featureVisibility";

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

type TrainingAssignment = {
  assignment_id: string;
  course_id: string;
  worker_id: number;
  worker_name?: string | null;
  status: "assigned" | "in_progress" | "completed" | "overdue";
  assigned_at: string;
  due_at?: string | null;
  completed_at?: string | null;
  score?: number | null;
};

type TrainingAssignmentListResponse = {
  items: TrainingAssignment[];
  total: number;
};

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parseWorkerIds(raw: string) {
  return raw
    .split(/[,\s]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => Number(entry))
    .filter((value) => Number.isFinite(value));
}

export default function TrainingCourseDetailPage() {
  const params = useParams();
  const courseIdParam = params?.course_id;
  const courseId = Array.isArray(courseIdParam) ? courseIdParam[0] : courseIdParam;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [course, setCourse] = useState<TrainingCourse | null>(null);
  const [assignments, setAssignments] = useState<TrainingAssignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assignmentError, setAssignmentError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [assignWorkerIds, setAssignWorkerIds] = useState("");
  const [assignDueAt, setAssignDueAt] = useState("");
  const [assignSubmitting, setAssignSubmitting] = useState(false);
  const [updateSubmitting, setUpdateSubmitting] = useState<string | null>(null);

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

  const loadCourse = useCallback(async () => {
    if (!username || !password || !courseId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/training/courses/${courseId}`, {
        headers: authHeaders,
      });
      if (!response.ok) throw new Error(`Failed (${response.status})`);
      const data = (await response.json()) as TrainingCourse;
      setCourse(data);
    } catch (err) {
      console.error("Failed to load course", err);
      setError("Unable to load training course.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, courseId, password, username]);

  const loadAssignments = useCallback(async () => {
    if (!username || !password || !courseId) return;
    setAssignmentError(null);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/training/courses/${courseId}/assignments`,
        { headers: authHeaders }
      );
      if (!response.ok) throw new Error(`Failed (${response.status})`);
      const data = (await response.json()) as TrainingAssignmentListResponse;
      setAssignments(data.items);
    } catch (err) {
      console.error("Failed to load assignments", err);
      setAssignmentError("Unable to load assignments.");
    }
  }, [authHeaders, courseId, password, username]);

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
    loadCourse();
    loadAssignments();
  }, [loadAssignments, loadCourse, pageVisible]);

  const openAssignModal = useCallback(() => {
    setAssignWorkerIds("");
    setAssignDueAt("");
    setAssignmentError(null);
    setAssignModalOpen(true);
  }, []);

  const closeAssignModal = useCallback(() => {
    setAssignModalOpen(false);
    setAssignSubmitting(false);
  }, []);

  const handleAssign = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!username || !password || !courseId) return;
      const workerIds = parseWorkerIds(assignWorkerIds);
      if (!workerIds.length) {
        setAssignmentError("Enter at least one worker ID.");
        return;
      }
      setAssignSubmitting(true);
      setAssignmentError(null);
      setStatusMessage(null);
      try {
        const payload = {
          worker_ids: workerIds,
          due_at: assignDueAt ? new Date(assignDueAt).toISOString() : null,
        };
        const response = await fetch(`${API_BASE}/v1/admin/training/courses/${courseId}/assign`, {
          method: "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed (${response.status})`);
        setStatusMessage("Assignments created.");
        setAssignModalOpen(false);
        await loadAssignments();
      } catch (err) {
        console.error("Failed to assign course", err);
        setAssignmentError("Unable to assign course.");
      } finally {
        setAssignSubmitting(false);
      }
    },
    [assignDueAt, assignWorkerIds, authHeaders, courseId, loadAssignments, password, username]
  );

  const handleAssignmentUpdate = useCallback(
    async (assignmentId: string, status: TrainingAssignment["status"], score?: number | null) => {
      if (!username || !password) return;
      setUpdateSubmitting(assignmentId);
      setStatusMessage(null);
      setAssignmentError(null);
      try {
        const response = await fetch(`${API_BASE}/v1/admin/training/assignments/${assignmentId}`, {
          method: "PATCH",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify({ status, score }),
        });
        if (!response.ok) throw new Error(`Failed (${response.status})`);
        const updated = (await response.json()) as TrainingAssignment;
        setAssignments((prev) =>
          prev.map((assignment) =>
            assignment.assignment_id === assignmentId ? { ...assignment, ...updated } : assignment
          )
        );
        setStatusMessage("Assignment updated.");
      } catch (err) {
        console.error("Failed to update assignment", err);
        setAssignmentError("Unable to update assignment.");
      } finally {
        setUpdateSubmitting(null);
      }
    },
    [authHeaders, password, username]
  );

  const handleStatusChange = useCallback(
    (assignmentId: string, status: TrainingAssignment["status"]) => {
      setAssignments((prev) =>
        prev.map((assignment) =>
          assignment.assignment_id === assignmentId ? { ...assignment, status } : assignment
        )
      );
    },
    []
  );

  const handleScoreChange = useCallback((assignmentId: string, scoreValue: string) => {
    const trimmed = scoreValue.trim();
    const parsed = trimmed.length ? Number(trimmed) : null;
    setAssignments((prev) =>
      prev.map((assignment) =>
        assignment.assignment_id === assignmentId
          ? {
              ...assignment,
              score: parsed === null ? null : Number.isFinite(parsed) ? parsed : assignment.score ?? null,
            }
          : assignment
      )
    );
  }, []);

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
            <h1>Course detail</h1>
            <p className="muted">Assignments and completion tracking for this course.</p>
          </div>
          <div className="admin-actions">
            <Link className="btn btn-ghost" href="/admin/training/courses">
              Back to courses
            </Link>
            <Link className="btn btn-ghost" href="/admin/training/calendar">
              Training calendar
            </Link>
            {canManage ? (
              <button className="btn btn-primary" type="button" onClick={openAssignModal}>
                Assign workers
              </button>
            ) : null}
          </div>
        </div>
        <div className="card-body">
          {statusMessage ? <div className="success">{statusMessage}</div> : null}
          {error ? <div className="error">{error}</div> : null}
          {loading ? (
            <p className="muted">Loading course...</p>
          ) : course ? (
            <div className="card admin-card">
              <div className="card-header">
                <div>
                  <strong>{course.title}</strong>
                  <div className="muted">{course.description ?? "No description"}</div>
                </div>
                <div className="pill-row">
                  <span className="pill">Format: {course.format ?? "—"}</span>
                  <span className="pill">Duration: {course.duration_minutes ?? "—"} min</span>
                  <span className="pill">{course.active ? "Active" : "Inactive"}</span>
                </div>
              </div>
            </div>
          ) : null}
          <div className="card admin-card">
            <div className="card-header">
              <div>
                <strong>Assignments</strong>
                <div className="muted">Track worker progress and completion status.</div>
              </div>
            </div>
            <div className="card-body">
              {assignmentError ? <div className="error">{assignmentError}</div> : null}
              {assignments.length ? (
                <table className="table-like">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>Status</th>
                      <th>Assigned</th>
                      <th>Due</th>
                      <th>Completed</th>
                      <th>Score</th>
                      {canManage ? <th>Actions</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.map((assignment) => (
                      <tr key={assignment.assignment_id}>
                        <td>
                          <div>{assignment.worker_name ?? `Worker #${assignment.worker_id}`}</div>
                          <div className="muted">ID {assignment.worker_id}</div>
                        </td>
                        <td>
                          {canManage ? (
                            <select
                              value={assignment.status}
                              onChange={(event) =>
                                handleStatusChange(
                                  assignment.assignment_id,
                                  event.target.value as TrainingAssignment["status"]
                                )
                              }
                            >
                              <option value="assigned">Assigned</option>
                              <option value="in_progress">In progress</option>
                              <option value="completed">Completed</option>
                              <option value="overdue">Overdue</option>
                            </select>
                          ) : (
                            <span className={`status-badge ${assignment.status}`}>
                              {assignment.status.replace("_", " ")}
                            </span>
                          )}
                        </td>
                        <td>{formatDateTime(assignment.assigned_at)}</td>
                        <td>{formatDateTime(assignment.due_at)}</td>
                        <td>{formatDateTime(assignment.completed_at)}</td>
                        <td>
                          {canManage ? (
                            <input
                              type="number"
                              min="0"
                              max="100"
                              defaultValue={assignment.score ?? ""}
                              onChange={(event) => handleScoreChange(assignment.assignment_id, event.target.value)}
                            />
                          ) : assignment.score != null ? (
                            assignment.score
                          ) : (
                            "—"
                          )}
                        </td>
                        {canManage ? (
                          <td>
                            <button
                              className="btn btn-secondary"
                              type="button"
                              disabled={updateSubmitting === assignment.assignment_id}
                              onClick={() =>
                                handleAssignmentUpdate(assignment.assignment_id, assignment.status, assignment.score)
                              }
                            >
                              {updateSubmitting === assignment.assignment_id ? "Saving..." : "Save"}
                            </button>
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted">No assignments yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {assignModalOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeAssignModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "640px" }}>
            <header className="schedule-modal-header">
              <div>
                <strong>Assign workers</strong>
                <div className="muted">Enter worker IDs to assign this course.</div>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeAssignModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body">
              <form className="stack" onSubmit={handleAssign}>
                <label className="stack">
                  <span>Worker IDs</span>
                  <textarea
                    rows={3}
                    placeholder="e.g. 12, 24, 31"
                    value={assignWorkerIds}
                    onChange={(event) => setAssignWorkerIds(event.target.value)}
                  />
                </label>
                <label className="stack">
                  <span>Due date</span>
                  <input
                    type="date"
                    value={assignDueAt}
                    onChange={(event) => setAssignDueAt(event.target.value)}
                  />
                </label>
                <button className="btn btn-primary" type="submit" disabled={assignSubmitting}>
                  {assignSubmitting ? "Assigning..." : "Assign workers"}
                </button>
              </form>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
