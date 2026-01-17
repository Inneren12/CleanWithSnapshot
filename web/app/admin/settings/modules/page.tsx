"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type FeatureTreeItem,
  type UiPrefsResponse,
  FEATURE_MODULE_TREE,
  filterFeatureTree,
  isHidden,
  isVisible,
} from "../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function renderTree(
  items: FeatureTreeItem[],
  options: {
    depth?: number;
    featureConfig: FeatureConfigResponse;
    uiPrefs: UiPrefsResponse;
    isOwner: boolean;
    onToggleOrg: (key: string, enabled: boolean) => void;
    onToggleHidden: (key: string, hidden: boolean) => void;
  }
): JSX.Element[] {
  const { depth = 0, featureConfig, uiPrefs, isOwner, onToggleOrg, onToggleHidden } = options;
  return items.flatMap((item) => {
    const orgEnabled = featureConfig.effective[item.key] ?? true;
    const hidden = isHidden(uiPrefs.hidden_keys, item.key);
    const row = (
      <div key={item.key} className="settings-row" style={{ paddingLeft: depth * 16 }}>
        <div className="settings-info">
          <div className="settings-title">
            <strong>{item.label}</strong>
            <span className="settings-key">{item.key}</span>
          </div>
          {item.description ? <div className="muted">{item.description}</div> : null}
        </div>
        <div className="settings-toggles">
          <label className="settings-toggle">
            <span className="muted">Org enabled</span>
            <input
              type="checkbox"
              checked={orgEnabled}
              onChange={(event) => onToggleOrg(item.key, event.target.checked)}
              disabled={!isOwner}
            />
          </label>
          <label className="settings-toggle">
            <span className="muted">Hide for me</span>
            <input
              type="checkbox"
              checked={hidden}
              onChange={(event) => onToggleHidden(item.key, event.target.checked)}
            />
          </label>
        </div>
      </div>
    );
    const children = item.children?.length
      ? renderTree(item.children, {
          ...options,
          depth: depth + 1,
        })
      : [];
    return [row, ...children];
  });
}

export default function ModulesVisibilityPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const isOwner = profile?.role === "owner";
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("api.settings", profile?.permissions, featureOverrides, hiddenKeys)
    : true;

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
      {
        key: "org-settings",
        label: "Org Settings",
        href: "/admin/settings/org",
        featureKey: "module.settings",
      },
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
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
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
      .filter(
        (entry) => !entry.requiresPermission || profile.permissions.includes(entry.requiresPermission)
      )
      .filter((entry) => isVisible(entry.featureKey, profile.permissions, featureOverrides, hiddenKeys))
      .map(({ featureKey, requiresPermission, ...link }) => link);
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
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } else {
      setFeatureConfig(null);
      setSettingsError("Failed to load module settings");
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    } else {
      setUiPrefs(null);
      setSettingsError("Failed to load UI preferences");
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
  }, [loadFeatureConfig, loadProfile, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    setStatusMessage("Saved credentials");
  };

  const handleClearCredentials = () => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setSettingsError(null);
    setStatusMessage("Cleared credentials");
  };

  const handleToggleOrg = async (key: string, enabled: boolean) => {
    if (!featureConfig || !isOwner) return;
    setStatusMessage(null);
    const overrides = { ...featureConfig.overrides, [key]: enabled };
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ overrides }),
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
      setStatusMessage("Updated org module settings");
    } else {
      setStatusMessage("Failed to update org settings");
    }
  };

  const handleToggleHidden = async (key: string, hidden: boolean) => {
    if (!uiPrefs) return;
    setStatusMessage(null);
    const hiddenSet = new Set(uiPrefs.hidden_keys);
    if (hidden) {
      hiddenSet.add(key);
    } else {
      hiddenSet.delete(key);
    }
    const hiddenKeys = Array.from(hiddenSet);
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ hidden_keys: hiddenKeys }),
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
      setStatusMessage("Updated your visibility preferences");
    } else {
      setStatusMessage("Failed to update preferences");
    }
  };

  const filteredTree = useMemo(
    () => filterFeatureTree(FEATURE_MODULE_TREE, searchTerm),
    [searchTerm]
  );

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="modules" />
        <div className="admin-card admin-section">
          <h1>Modules & Visibility</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="modules" />
      <div className="admin-section">
        <h1>Modules & Visibility</h1>
        <p className="muted">
          Configure org-wide module access and personal UI visibility. Changes default to enabled unless
          explicitly disabled.
        </p>
      </div>

      {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}

      <div className="admin-card admin-section">
        <h2>Credentials</h2>
        <div className="admin-actions">
          <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="btn btn-primary" type="button" onClick={handleSaveCredentials}>
            Save
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear
          </button>
        </div>
        {statusMessage ? <p className="alert alert-success">{statusMessage}</p> : null}
        {!isOwner ? (
          <p className="muted">Only Owners can change org-level module switches.</p>
        ) : null}
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <h2>Module tree</h2>
          <p className="muted">Search and toggle modules or sub-features.</p>
        </div>
        <div className="admin-actions">
          <input
            placeholder="Search modules"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
          />
          <button
            className="btn btn-ghost"
            type="button"
            onClick={() => {
              setSearchTerm("");
              void loadFeatureConfig();
              void loadUiPrefs();
            }}
          >
            Refresh
          </button>
        </div>
        {!featureConfig || !uiPrefs ? (
          <p className="muted">Load credentials to view module settings.</p>
        ) : filteredTree.length ? (
          <div className="settings-tree">
            {renderTree(filteredTree, {
              featureConfig,
              uiPrefs,
              isOwner: Boolean(isOwner),
              onToggleOrg: handleToggleOrg,
              onToggleHidden: handleToggleHidden,
            })}
          </div>
        ) : (
          <p className="muted">No modules match your search.</p>
        )}
      </div>
    </div>
  );
}
