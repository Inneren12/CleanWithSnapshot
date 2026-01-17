export type FeatureConfigResponse = {
  org_id: string;
  overrides: Record<string, boolean>;
  defaults: Record<string, boolean>;
  effective: Record<string, boolean>;
  keys: string[];
};

export type UiPrefsResponse = {
  hidden_keys: string[];
};

export type AdminProfile = {
  username: string;
  role: string;
  permissions: string[];
};

export type FeatureTreeItem = {
  key: string;
  label: string;
  description?: string;
  children?: FeatureTreeItem[];
};

const MODULE_PERMISSIONS: Record<string, string> = {
  dashboard: "core.view",
  schedule: "bookings.view",
  invoices: "invoices.view",
  quality: "bookings.view",
  teams: "core.view",
  analytics: "finance.view",
  finance: "finance.view",
  pricing: "settings.manage",
  marketing: "settings.manage",
  leads: "contacts.view",
  inventory: "inventory.view",
  training: "core.view",
  notifications_center: "core.view",
  settings: "settings.manage",
  integrations: "settings.manage",
  api: "settings.manage",
};

export const FEATURE_MODULE_TREE: FeatureTreeItem[] = [
  {
    key: "module.dashboard",
    label: "Dashboard",
    description: "Core admin overview widgets.",
    children: [{ key: "dashboard.weather", label: "Weather context" }],
  },
  {
    key: "module.schedule",
    label: "Schedule",
    description: "Dispatcher timeline and assignment tools.",
    children: [{ key: "schedule.optimization_ai", label: "AI optimization suggestions" }],
  },
  { key: "module.invoices", label: "Invoices" },
  { key: "module.quality", label: "Quality" },
  { key: "module.teams", label: "Teams" },
  { key: "module.analytics", label: "Analytics" },
  {
    key: "module.finance",
    label: "Finance",
    children: [
      { key: "finance.reports", label: "Reports dashboard" },
      { key: "finance.cash_flow", label: "Cash flow widget" },
    ],
  },
  {
    key: "module.pricing",
    label: "Pricing & Policies",
    description: "Service catalog, pricing rules, and booking policies.",
    children: [
      { key: "pricing.service_types", label: "Service types & pricing" },
      { key: "pricing.booking_policies", label: "Booking policies" },
    ],
  },
  {
    key: "module.marketing",
    label: "Marketing",
    children: [
      { key: "marketing.analytics", label: "Lead source analytics" },
      { key: "marketing.email_campaigns", label: "Email campaigns" },
      { key: "marketing.email_segments", label: "Email segments" },
      { key: "marketing.promo_codes", label: "Promo codes" },
    ],
  },
  { key: "module.leads", label: "Leads" },
  { key: "module.inventory", label: "Inventory" },
  { key: "module.training", label: "Training" },
  { key: "module.notifications_center", label: "Notifications center" },
  {
    key: "module.settings",
    label: "Settings",
    description: "Organization profile, hours, and holidays.",
  },
  {
    key: "module.integrations",
    label: "Integrations",
    description: "Payments, messaging, and email providers.",
  },
  {
    key: "module.api",
    label: "API & Integrations",
    children: [{ key: "api.settings", label: "Modules & visibility settings" }],
  },
];

export const FEATURE_KEYS: string[] = FEATURE_MODULE_TREE.flatMap((item) => [
  item.key,
  ...(item.children?.map((child) => child.key) ?? []),
]);

export function moduleBaseForKey(key: string): string {
  const trimmed = key.trim();
  if (trimmed.startsWith("module.")) {
    return trimmed.split(".", 2)[1];
  }
  return trimmed.split(".", 2)[0];
}

export function moduleKeyForBase(base: string): string {
  return `module.${base}`;
}

export function effectiveFeatureEnabled(overrides: Record<string, boolean>, key: string): boolean {
  const trimmed = key.trim();
  const base = moduleBaseForKey(trimmed);
  const moduleKey = moduleKeyForBase(base);
  const moduleOverride = overrides[moduleKey];
  if (moduleOverride === false) return false;
  if (Object.prototype.hasOwnProperty.call(overrides, trimmed)) {
    return Boolean(overrides[trimmed]);
  }
  if (moduleOverride === true) return true;
  return true;
}

export function isHidden(hiddenKeys: string[], key: string): boolean {
  const trimmed = key.trim();
  const base = moduleBaseForKey(trimmed);
  const moduleKey = moduleKeyForBase(base);
  const normalized = new Set(hiddenKeys.map((entry) => entry.trim()));
  return normalized.has(trimmed) || normalized.has(moduleKey);
}

export function permissionsAllow(permissions: string[] | undefined, key: string): boolean {
  if (!permissions) return false;
  const base = moduleBaseForKey(key);
  const required = MODULE_PERMISSIONS[base] ?? "core.view";
  return permissions.includes(required);
}

export function isVisible(
  key: string,
  permissions: string[] | undefined,
  overrides: Record<string, boolean>,
  hiddenKeys: string[]
): boolean {
  if (!permissionsAllow(permissions, key)) return false;
  if (isHidden(hiddenKeys, key)) return false;
  return effectiveFeatureEnabled(overrides, key);
}

export function filterFeatureTree(items: FeatureTreeItem[], term: string): FeatureTreeItem[] {
  const normalized = term.trim().toLowerCase();
  if (!normalized) return items;
  const filtered: FeatureTreeItem[] = [];
  for (const item of items) {
    const children = item.children ? filterFeatureTree(item.children, term) : undefined;
    const match =
      item.label.toLowerCase().includes(normalized) ||
      item.key.toLowerCase().includes(normalized) ||
      (item.description ?? "").toLowerCase().includes(normalized);
    if (match || (children && children.length > 0)) {
      filtered.push(children ? { ...item, children } : { ...item });
    }
  }
  return filtered;
}
