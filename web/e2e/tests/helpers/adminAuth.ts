import crypto from 'crypto';
import type { APIRequestContext, Page } from '@playwright/test';

const STORAGE_USERNAME_KEY = 'admin_basic_username';
const STORAGE_PASSWORD_KEY = 'admin_basic_password';

export type AdminCredentials = {
  username: string;
  password: string;
  apiBaseUrl: string;
};

export const defaultAdminCredentials = (): AdminCredentials => ({
  username: process.env.ADMIN_BASIC_USERNAME ?? 'admin',
  password: process.env.ADMIN_BASIC_PASSWORD ?? 'admin123',
  apiBaseUrl:
    process.env.PLAYWRIGHT_API_BASE_URL ??
    process.env.E2E_API_BASE_URL ??
    'http://127.0.0.1:8000',
});

const proxyAuthEnabled =
  process.env.E2E_PROXY_AUTH_ENABLED === 'true' ||
  Boolean(process.env.E2E_PROXY_AUTH_SECRET) ||
  process.env.ADMIN_PROXY_AUTH_ENABLED === 'true';

const buildProxyHeaders = (
  username: string,
  email: string,
  roles: string,
  secret: string
): Record<string, string> => {
  const timestamp = Math.floor(Date.now() / 1000);
  const canonical = `${username}|${email}|${roles}|${timestamp}`;
  const signature = crypto
    .createHmac('sha256', secret)
    .update(canonical)
    .digest('hex');

  return {
    'X-Proxy-Admin-User': username,
    'X-Proxy-Admin-Email': email,
    'X-Proxy-Admin-Roles': roles,
    'X-Proxy-Admin-Timestamp': String(timestamp),
    'X-Proxy-Admin-Signature': signature,
  };
};

export async function verifyAdminCredentials(
  request: APIRequestContext,
  { username, password, apiBaseUrl }: AdminCredentials
): Promise<void> {
  const roles = process.env.E2E_PROXY_ADMIN_ROLES ?? 'admin';
  const email = process.env.E2E_PROXY_ADMIN_EMAIL ?? username;
  const proxySecret = process.env.E2E_PROXY_AUTH_SECRET ?? '';
  if (proxyAuthEnabled && !proxySecret) {
    throw new Error('E2E proxy auth enabled but E2E_PROXY_AUTH_SECRET is missing');
  }
  const response = await request.get(`${apiBaseUrl}/v1/admin/profile`, {
    headers: proxyAuthEnabled && proxySecret
      ? buildProxyHeaders(username, email, roles, proxySecret)
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
