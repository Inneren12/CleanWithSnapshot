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

type PermissionCatalogEntry = {
  key: string;
  label: string;
  description: string;
  group?: string | null;
};

type RoleEntry = {
  role_id?: string | null;
  key: string;
  name: string;
  description?: string | null;
  permissions: string[];
  builtin: boolean;
};

type RoleListResponse = {
  roles: RoleEntry[];
};

type PermissionCatalogResponse = {
  permissions: PermissionCatalogEntry[];
};

type AdminUser = {
  membership_id: number;
  user_id: string;
  email: string;
  role: string;
  role_key: string;
  custom_role_id?: string | null;
  membership_active: boolean;
  user_active: boolean;
  must_change_password: boolean;
};

type AdminUserListResponse = {
  users: AdminUser[];
};

export default function RolesPermissionsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [roles, setRoles] = useState<RoleEntry[]>([]);
  const [permissions, setPermissions] = useState<PermissionCatalogEntry[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [advancedMode, setAdvancedMode] = useState(false);
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDescription, setNewRoleDescription] = useState("");
  const [newRolePermissions, setNewRolePermissions] = useState<Set<string>>(new Set());
  const [editingRole, setEditingRole] = useState<RoleEntry | null>(null);
  const [editPermissions, setEditPermissions] = useState<Set<string>>(new Set());

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const permissionKeys = profile?.permissions ?? [];
  const canManageUsers = permissionKeys.includes("users.manage");
  const canManageRoles = canManageUsers && profile?.role === "owner";

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
      { key: "roles", label: "Roles & Permissions", href: "/admin/iam/roles", featureKey: "module.teams" },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, profile.permissions, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
  }, [featureOverrides, hiddenKeys, profile, visibilityReady]);

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
    }
  }, [authHeaders, password, username]);

  const loadRoles = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/iam/roles`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as RoleListResponse;
      setRoles(data.roles);
    }
  }, [authHeaders, password, username]);

  const loadPermissions = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/iam/permissions`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as PermissionCatalogResponse;
      setPermissions(data.permissions);
    }
  }, [authHeaders, password, username]);

  const loadUsers = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/iam/users`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as AdminUserListResponse;
      setUsers(data.users);
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadRoles();
    void loadPermissions();
    void loadUsers();
  }, [loadFeatureConfig, loadPermissions, loadProfile, loadRoles, loadUiPrefs, loadUsers]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadRoles();
    void loadPermissions();
    void loadUsers();
    setStatusMessage("Saved credentials");
  };

  const handleClearCredentials = () => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setProfile(null);
    setRoles([]);
    setPermissions([]);
    setUsers([]);
    setStatusMessage("Cleared credentials");
  };

  const togglePermission = (
    key: string,
    setState: (value: Set<string>) => void,
    current: Set<string>
  ) => {
    const next = new Set(current);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    setState(next);
  };

  const handleCreateRole = async () => {
    if (!canManageRoles) return;
    setErrorMessage(null);
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/iam/roles`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({
        name: newRoleName,
        description: newRoleDescription || null,
        permissions: Array.from(newRolePermissions),
      }),
    });
    if (response.ok) {
      setNewRoleName("");
      setNewRoleDescription("");
      setNewRolePermissions(new Set());
      await loadRoles();
      setStatusMessage("Custom role created");
    } else {
      setErrorMessage("Failed to create role");
    }
  };

  const handleUpdateRole = async () => {
    if (!canManageRoles || !editingRole?.role_id) return;
    setErrorMessage(null);
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/iam/roles/${editingRole.role_id}`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({
        name: editingRole.name,
        description: editingRole.description ?? null,
        permissions: Array.from(editPermissions),
      }),
    });
    if (response.ok) {
      await loadRoles();
      setStatusMessage("Role updated");
    } else {
      setErrorMessage("Failed to update role");
    }
  };

  const handleDeleteRole = async (roleId?: string | null) => {
    if (!canManageRoles || !roleId) return;
    setErrorMessage(null);
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/iam/roles/${roleId}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.ok) {
      await loadRoles();
      setStatusMessage("Role deleted");
      if (editingRole?.role_id === roleId) {
        setEditingRole(null);
        setEditPermissions(new Set());
      }
    } else {
      setErrorMessage("Failed to delete role");
    }
  };

  const handleAssignRole = async (user: AdminUser, value: string) => {
    if (!canManageUsers) return;
    setErrorMessage(null);
    setStatusMessage(null);
    const payload: Record<string, string> = {};
    if (value.startsWith("custom:")) {
      payload.custom_role_id = value.replace("custom:", "");
    } else {
      payload.role = value.replace("builtin:", "");
    }
    const response = await fetch(`${API_BASE}/v1/admin/iam/users/${user.user_id}/role`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      await loadUsers();
      setStatusMessage("Updated user role");
    } else {
      setErrorMessage("Failed to update user role");
    }
  };

  const groupedPermissions = useMemo(() => {
    const grouped: Record<string, PermissionCatalogEntry[]> = {};
    permissions.forEach((entry) => {
      const group = entry.group ?? "other";
      grouped[group] = grouped[group] ?? [];
      grouped[group].push(entry);
    });
    return grouped;
  }, [permissions]);

  const sortedRoles = useMemo(() => {
    return [...roles].sort((a, b) => a.name.localeCompare(b.name));
  }, [roles]);

  const roleOptions = useMemo(() => {
    return sortedRoles.map((role) => ({
      value: role.builtin ? `builtin:${role.key}` : `custom:${role.role_id}`,
      label: role.name,
    }));
  }, [sortedRoles]);

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="roles" />
      <div className="admin-section">
        <h1>Roles & Permissions</h1>
        <p className="muted">
          Manage built-in roles and custom permission matrices. Built-in roles are read-only.
        </p>
      </div>

      {errorMessage ? <p className="alert alert-warning">{errorMessage}</p> : null}
      {statusMessage ? <p className="alert alert-info">{statusMessage}</p> : null}

      <div className="admin-card">
        <div className="admin-section">
          <h2>Credentials</h2>
          <div className="admin-actions">
            <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
            <input
              placeholder="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button className="btn" type="button" onClick={handleSaveCredentials}>
              Save
            </button>
            <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
              Clear
            </button>
          </div>
        </div>
      </div>

      <div className="admin-card">
        <div className="admin-section">
          <h2>Role catalog</h2>
          <div className="admin-actions" style={{ justifyContent: "space-between" }}>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={advancedMode}
                onChange={(event) => setAdvancedMode(event.target.checked)}
              />
              <span>Advanced mode</span>
            </label>
            {!canManageRoles ? (
              <span className="muted">Owner permission required to edit roles.</span>
            ) : null}
          </div>
        </div>
        <div className="admin-section">
          {sortedRoles.map((role) => (
            <div key={role.key} className="settings-row" style={{ alignItems: "flex-start" }}>
              <div className="settings-info">
                <div className="settings-title">
                  <strong>{role.name}</strong>
                  <span className="settings-key">{role.key}</span>
                  {role.builtin ? <span className="pill">Built-in</span> : null}
                </div>
                {role.description ? <div className="muted">{role.description}</div> : null}
                <div className="chip-row">
                  {role.permissions.map((permission) => (
                    <span key={permission} className="chip chip-muted">
                      {permission}
                    </span>
                  ))}
                </div>
              </div>
              {!role.builtin && canManageRoles ? (
                <div className="admin-actions">
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => {
                      setEditingRole({ ...role });
                      setEditPermissions(new Set(role.permissions));
                    }}
                  >
                    Edit
                  </button>
                  <button className="btn btn-danger" type="button" onClick={() => handleDeleteRole(role.role_id)}>
                    Delete
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="admin-card">
        <div className="admin-section">
          <h2>Create custom role</h2>
          <div className="settings-row" style={{ alignItems: "flex-start" }}>
            <div className="settings-info">
              <label className="stack">
                <span className="label">Role name</span>
                <input
                  value={newRoleName}
                  onChange={(event) => setNewRoleName(event.target.value)}
                  placeholder="e.g. Team Lead"
                />
              </label>
              <label className="stack">
                <span className="label">Description</span>
                <input
                  value={newRoleDescription}
                  onChange={(event) => setNewRoleDescription(event.target.value)}
                  placeholder="Optional summary"
                />
              </label>
            </div>
            <div className="admin-actions">
              <button className="btn" type="button" onClick={handleCreateRole} disabled={!canManageRoles}>
                Create role
              </button>
            </div>
          </div>
          {advancedMode ? (
            <div className="permissions-grid">
              {Object.entries(groupedPermissions).map(([group, entries]) => (
                <div key={group} className="permissions-group">
                  <h4>{group}</h4>
                  {entries.map((entry) => (
                    <label key={entry.key} className="permission-row">
                      <input
                        type="checkbox"
                        checked={newRolePermissions.has(entry.key)}
                        onChange={() => togglePermission(entry.key, setNewRolePermissions, newRolePermissions)}
                        disabled={!canManageRoles}
                      />
                      <span>
                        <strong>{entry.label}</strong>
                        <span className="muted">{entry.key}</span>
                      </span>
                      <span className="muted">{entry.description}</span>
                    </label>
                  ))}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {editingRole ? (
        <div className="admin-card">
          <div className="admin-section">
            <h2>Edit custom role</h2>
            <div className="settings-row" style={{ alignItems: "flex-start" }}>
              <div className="settings-info">
                <label className="stack">
                  <span className="label">Role name</span>
                  <input
                    value={editingRole.name}
                    onChange={(event) =>
                      setEditingRole((prev) => (prev ? { ...prev, name: event.target.value } : prev))
                    }
                  />
                </label>
                <label className="stack">
                  <span className="label">Description</span>
                  <input
                    value={editingRole.description ?? ""}
                    onChange={(event) =>
                      setEditingRole((prev) =>
                        prev ? { ...prev, description: event.target.value } : prev
                      )
                    }
                  />
                </label>
              </div>
              <div className="admin-actions">
                <button className="btn" type="button" onClick={handleUpdateRole} disabled={!canManageRoles}>
                  Save changes
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => {
                    setEditingRole(null);
                    setEditPermissions(new Set());
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
            {advancedMode ? (
              <div className="permissions-grid">
                {Object.entries(groupedPermissions).map(([group, entries]) => (
                  <div key={group} className="permissions-group">
                    <h4>{group}</h4>
                    {entries.map((entry) => (
                      <label key={entry.key} className="permission-row">
                        <input
                          type="checkbox"
                          checked={editPermissions.has(entry.key)}
                          onChange={() => togglePermission(entry.key, setEditPermissions, editPermissions)}
                          disabled={!canManageRoles}
                        />
                        <span>
                          <strong>{entry.label}</strong>
                          <span className="muted">{entry.key}</span>
                        </span>
                        <span className="muted">{entry.description}</span>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="admin-card">
        <div className="admin-section">
          <h2>User assignments</h2>
          {!canManageUsers ? (
            <p className="muted">You need user management permissions to update assignments.</p>
          ) : null}
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const currentValue = user.custom_role_id
                    ? `custom:${user.custom_role_id}`
                    : `builtin:${user.role_key}`;
                  return (
                    <tr key={user.user_id}>
                      <td>{user.email}</td>
                      <td>
                        <select
                          value={currentValue}
                          onChange={(event) => handleAssignRole(user, event.target.value)}
                          disabled={!canManageUsers}
                        >
                          {roleOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {user.user_active && user.membership_active ? "Active" : "Inactive"}
                        {user.must_change_password ? " · Password reset" : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
