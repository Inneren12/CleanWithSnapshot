import { beforeEach, describe, expect, it } from "vitest";

import {
  ADMIN_STORAGE_PASSWORD_KEY,
  ADMIN_STORAGE_USERNAME_KEY,
  getCsrfToken,
  resolveAdminRequestHeaders,
} from "../app/admin/lib/adminAuth";

describe("adminAuth csrf wiring", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
  });

  it("reads csrf token from cookie", () => {
    document.cookie = "csrf_token=test-csrf; path=/";
    expect(getCsrfToken()).toBe("test-csrf");
  });

  it("injects csrf header for authenticated requests", () => {
    window.localStorage.setItem(ADMIN_STORAGE_USERNAME_KEY, "admin");
    window.localStorage.setItem(ADMIN_STORAGE_PASSWORD_KEY, "secret");
    document.cookie = "csrf_token=test-csrf; path=/";

    const resolved = resolveAdminRequestHeaders();

    expect(resolved.hasCredentials).toBe(true);
    expect(resolved.headers.Authorization).toBeDefined();
    expect(resolved.headers["X-CSRF-Token"]).toBe("test-csrf");
  });
});
