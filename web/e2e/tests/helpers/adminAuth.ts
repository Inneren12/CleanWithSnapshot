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
  apiBaseUrl: process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://localhost:8000',
});

export async function verifyAdminCredentials(
  request: APIRequestContext,
  { username, password, apiBaseUrl }: AdminCredentials
): Promise<void> {
  const authHeader = Buffer.from(`${username}:${password}`).toString('base64');
  const response = await request.get(`${apiBaseUrl}/v1/admin/profile`, {
    headers: {
      Authorization: `Basic ${authHeader}`,
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
