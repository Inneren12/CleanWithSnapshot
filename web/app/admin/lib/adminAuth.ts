export const ADMIN_STORAGE_USERNAME_KEY = "admin_basic_username";
export const ADMIN_STORAGE_PASSWORD_KEY = "admin_basic_password";

type AdminAuthResolution = {
  headers: Record<string, string>;
  hasCredentials: boolean;
};

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const encodedName = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie
    .split(";")
    .map((entry) => entry.trim())
    .find((entry) => entry.startsWith(encodedName));

  if (!cookie) {
    return null;
  }

  return decodeURIComponent(cookie.slice(encodedName.length));
}

export function getCsrfToken(): string | null {
  return readCookie("csrf_token");
}

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

export function resolveAdminRequestHeaders(
  username?: string,
  password?: string
): AdminAuthResolution {
  const auth = resolveAdminAuthHeaders(username, password);
  const csrfToken = getCsrfToken();
  if (!csrfToken) {
    return auth;
  }

  return {
    hasCredentials: auth.hasCredentials,
    headers: {
      ...auth.headers,
      "X-CSRF-Token": csrfToken,
    },
  };
}
