export const ADMIN_STORAGE_USERNAME_KEY = "admin_basic_username";
export const ADMIN_STORAGE_PASSWORD_KEY = "admin_basic_password";

type AdminAuthResolution = {
  headers: Record<string, string>;
  hasCredentials: boolean;
};

export function resolveAdminAuthHeaders(
  username?: string,
  password?: string
): AdminAuthResolution {
  let resolvedUsername = username?.trim() ?? "";
  let resolvedPassword = password?.trim() ?? "";

  if ((!resolvedUsername || !resolvedPassword) && typeof window !== "undefined") {
    resolvedUsername = window.localStorage.getItem(ADMIN_STORAGE_USERNAME_KEY) ?? "";
    resolvedPassword = window.localStorage.getItem(ADMIN_STORAGE_PASSWORD_KEY) ?? "";
  }

  if (!resolvedUsername || !resolvedPassword) {
    return { headers: {}, hasCredentials: false };
  }

  const encoded = btoa(`${resolvedUsername}:${resolvedPassword}`);
  return { headers: { Authorization: `Basic ${encoded}` }, hasCredentials: true };
}
