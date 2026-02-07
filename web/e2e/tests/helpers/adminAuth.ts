import crypto from 'crypto';
import type { APIRequestContext, Page } from '@playwright/test';

const STORAGE_USERNAME_KEY = 'admin_basic_username';
const STORAGE_PASSWORD_KEY = 'admin_basic_password';

export type AdminCredentials = {
  username: string;
  password: string;
  apiBaseUrl: string;
};

const ADMIN_PROXY_AUTH_ENABLED =
  (process.env.ADMIN_PROXY_AUTH_ENABLED ?? '').toLowerCase() === 'true';
const ADMIN_PROXY_AUTH_SECRET = process.env.ADMIN_PROXY_AUTH_SECRET ?? '';
const ADMIN_PROXY_AUTH_ROLE = process.env.ADMIN_PROXY_AUTH_ROLE ?? 'admin';
const ADMIN_PROXY_AUTH_E2E_ENABLED =
  (process.env.ADMIN_PROXY_AUTH_E2E_ENABLED ?? '').toLowerCase() === 'true';
const ADMIN_PROXY_AUTH_E2E_SECRET = process.env.ADMIN_PROXY_AUTH_E2E_SECRET ?? '';
const ADMIN_PROXY_AUTH_E2E_USER = process.env.ADMIN_PROXY_AUTH_E2E_USER ?? '';
const ADMIN_PROXY_AUTH_E2E_EMAIL = process.env.ADMIN_PROXY_AUTH_E2E_EMAIL ?? '';
const ADMIN_PROXY_AUTH_E2E_ROLES = process.env.ADMIN_PROXY_AUTH_E2E_ROLES ?? '';

export const defaultAdminCredentials = (): AdminCredentials => ({
  username: process.env.ADMIN_BASIC_USERNAME ?? 'admin',
  password: process.env.ADMIN_BASIC_PASSWORD ?? 'admin123',
  apiBaseUrl:
    process.env.PLAYWRIGHT_API_BASE_URL ??
    process.env.E2E_API_BASE_URL ??
    'http://127.0.0.1:3000',
});

const buildProxyHeaders = (credentials: AdminCredentials): Record<string, string> => {
  const mfaValue = 'true';
  const headers: Record<string, string> = {
    'X-Proxy-Auth-Secret': ADMIN_PROXY_AUTH_SECRET,
    'X-Auth-MFA': mfaValue,
  };

  if (ADMIN_PROXY_AUTH_E2E_ENABLED && ADMIN_PROXY_AUTH_E2E_SECRET) {
    const user = ADMIN_PROXY_AUTH_E2E_USER || credentials.username;
    const email =
      ADMIN_PROXY_AUTH_E2E_EMAIL || `${credentials.username}@example.com`;
    const roles = ADMIN_PROXY_AUTH_E2E_ROLES || ADMIN_PROXY_AUTH_ROLE;
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const payload = [user, email, roles, timestamp, mfaValue].join('\n');
    const signature = crypto
      .createHmac('sha256', ADMIN_PROXY_AUTH_E2E_SECRET)
      .update(payload)
      .digest('hex');
    headers['X-E2E-Admin-User'] = user;
    headers['X-E2E-Admin-Email'] = email;
    headers['X-E2E-Admin-Roles'] = roles;
    headers['X-E2E-Proxy-Timestamp'] = timestamp;
    headers['X-E2E-Proxy-Signature'] = signature;
    return headers;
  }

  headers['X-Admin-User'] = credentials.username;
  headers['X-Admin-Roles'] = ADMIN_PROXY_AUTH_ROLE;
  return headers;
};

export async function verifyAdminCredentials(
  request: APIRequestContext,
  { username, password, apiBaseUrl }: AdminCredentials
): Promise<void> {
  const response = await request.get(`${apiBaseUrl}/v1/admin/profile`, {
    headers: ADMIN_PROXY_AUTH_ENABLED
      ? buildProxyHeaders({ username, password, apiBaseUrl })
      : {
          Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`,
        },
  });

  if (!response.ok()) {
    throw new Error(
      `Admin auth failed (${response.status()}): ${await response.text()}`
    );
  }
}

export async function seedAdminStorage(
  page: Page,
  { username, password }: Pick<AdminCredentials, 'username' | 'password'>
): Promise<void> {
  if (ADMIN_PROXY_AUTH_ENABLED) {
    await page.context().setExtraHTTPHeaders(
      buildProxyHeaders({ username, password, apiBaseUrl: '' })
    );
  }
  await page.addInitScript(
    ({ userKey, passKey, usernameValue, passwordValue }) => {
      window.localStorage.setItem(userKey, usernameValue);
      window.localStorage.setItem(passKey, passwordValue);
    },
    {
      userKey: STORAGE_USERNAME_KEY,
      passKey: STORAGE_PASSWORD_KEY,
      usernameValue: username,
      passwordValue: password,
    }
  );
}
