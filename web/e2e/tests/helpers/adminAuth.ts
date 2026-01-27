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

export const defaultAdminCredentials = (): AdminCredentials => ({
  username: process.env.ADMIN_BASIC_USERNAME ?? 'admin',
  password: process.env.ADMIN_BASIC_PASSWORD ?? 'admin123',
  apiBaseUrl:
    process.env.PLAYWRIGHT_API_BASE_URL ??
    process.env.E2E_API_BASE_URL ??
    'http://127.0.0.1:8000',
});

const buildProxyHeaders = (credentials: AdminCredentials): Record<string, string> => {
  const headers: Record<string, string> = {
    'X-Admin-User': credentials.username,
    'X-Admin-Roles': ADMIN_PROXY_AUTH_ROLE,
    'X-Proxy-Auth-Secret': ADMIN_PROXY_AUTH_SECRET,
    'X-Auth-MFA': 'true',
  };

  if (ADMIN_PROXY_AUTH_E2E_ENABLED && ADMIN_PROXY_AUTH_E2E_SECRET) {
    const signature = crypto
      .createHmac('sha256', ADMIN_PROXY_AUTH_E2E_SECRET)
      .update('e2e-proxy-auth')
      .digest('hex');
    headers['X-E2E-Proxy-Signature'] = signature;
  }

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
