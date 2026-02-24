import crypto from 'crypto';
import type { APIRequestContext } from '@playwright/test';

import { AdminCredentials, defaultAdminCredentials } from './adminAuth';

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
const SAAS_E2E_EMAIL = process.env.SAAS_E2E_EMAIL;
const SAAS_E2E_ACCESS_TOKEN = process.env.SAAS_E2E_ACCESS_TOKEN;
const E2E_TEST_ORG = process.env.E2E_TEST_ORG;
const SAAS_E2E_PASSWORD =
  process.env.SAAS_E2E_PASSWORD ?? 'E2eDataRightsPassword1A';

const buildE2eEmail = (prefix: string): string =>
  `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;

export type DataExportResponse = {
  leads: Array<Record<string, unknown>>;
  bookings: Array<Record<string, unknown>>;
  invoices: Array<Record<string, unknown>>;
  payments: Array<Record<string, unknown>>;
  photos: Array<Record<string, unknown>>;
};

export type DataRightsExportRequestResponse = {
  export_id: string;
  status: string;
  created_at: string;
};

export type DataRightsExportListItem = {
  export_id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
};

export type DataRightsExportListResponse = {
  items: DataRightsExportListItem[];
  total: number;
};

export type DataDeletionResponse = {
  request_id: string;
  status: string;
  matched_leads: number;
  pending_deletions: number;
  requested_at: string;
};

type AdminUserCreateResponse = {
  user_id: string;
  email: string;
  target_type: string;
  must_change_password: boolean;
  temp_password: string;
};

type LoginResponse = {
  access_token: string;
  refresh_token?: string | null;
  org_id: string;
  role: string;
  expires_at?: string | null;
  must_change_password: boolean;
  mfa_verified: boolean;
};

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

function getAdminAuthHeaders(credentials: AdminCredentials): Record<string, string> {
  if (ADMIN_PROXY_AUTH_ENABLED) {
    return buildProxyHeaders(credentials);
  }
  return {
    Authorization: `Basic ${Buffer.from(`${credentials.username}:${credentials.password}`).toString('base64')}`,
  };
}

let cachedSaasAuthHeaders: Record<string, string> | null = null;
let cachedSaasAuthHeadersPromise: Promise<Record<string, string>> | null = null;
let saasAuthWorkerIndexOverride: number | null = null;

export function setSaasAuthWorkerIndex(index: number | null): void {
  saasAuthWorkerIndexOverride = index;
}

const resolveWorkerIndex = (): number => {
  if (saasAuthWorkerIndexOverride !== null) {
    return saasAuthWorkerIndexOverride;
  }
  const envCandidates = [
    process.env.PW_TEST_WORKER_INDEX,
    process.env.PLAYWRIGHT_WORKER_INDEX,
    process.env.TEST_WORKER_INDEX,
  ];
  for (const value of envCandidates) {
    if (value === undefined) continue;
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
};

const buildSaasE2eEmail = (suffix?: string): string => {
  if (SAAS_E2E_EMAIL) return SAAS_E2E_EMAIL;
  const workerIndex = resolveWorkerIndex();
  const label = suffix ? `-${suffix}` : '';
  return `e2e-data-rights-${workerIndex}${label}@example.com`;
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function getSaasAuthHeaders(
  request: APIRequestContext
): Promise<Record<string, string>> {
  console.log(
    '[E2E] SAAS_E2E_ACCESS_TOKEN present:',
    Boolean(process.env.SAAS_E2E_ACCESS_TOKEN)
  );
  if (SAAS_E2E_ACCESS_TOKEN) {
    cachedSaasAuthHeaders = {
      Authorization: `Bearer ${SAAS_E2E_ACCESS_TOKEN}`,
    };
    return cachedSaasAuthHeaders;
  }
  if (cachedSaasAuthHeaders) {
    return cachedSaasAuthHeaders;
  }
  if (cachedSaasAuthHeadersPromise) {
    return cachedSaasAuthHeadersPromise;
  }

  cachedSaasAuthHeadersPromise = (async () => {
    const credentials = defaultAdminCredentials();
    const createUser = async (email: string): Promise<AdminUserCreateResponse | null> => {
      const response = await request.post(`${credentials.apiBaseUrl}/v1/admin/users`, {
        headers: {
          ...getAdminAuthHeaders(credentials),
          ...(E2E_TEST_ORG ? { 'X-Test-Org': E2E_TEST_ORG } : {}),
          'Content-Type': 'application/json',
        },
        data: {
          email,
          target_type: 'client',
          name: 'E2E Data Rights',
          role: 'admin',
        },
      });

      if (response.status() === 409) {
        return null;
      }
      if (!response.ok()) {
        const text = await response.text();
        throw new Error(`Failed to create SaaS user (${response.status()}): ${text}`);
      }

      return (await response.json()) as AdminUserCreateResponse;
    };

    const loginWithPassword = async (email: string, password: string): Promise<LoginResponse> => {
      let lastStatus = 0;
      let lastBody = '';
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const response = await request.post(`${credentials.apiBaseUrl}/v1/auth/login`, {
          headers: {
            'Content-Type': 'application/json',
          },
          data: {
            email,
            password,
          },
        });

        if (response.ok()) {
          const payload = (await response.json()) as LoginResponse;
          if (!payload?.access_token) {
            throw new Error(
              `Login succeeded but no access_token in response. ` +
              `Status: ${response.status()}, Body: ${JSON.stringify(payload)}`
            );
          }
          return payload;
        }

        lastStatus = response.status();
        lastBody = await response.text();

        if (lastStatus === 401 && attempt < 2) {
          await sleep(500);
          continue;
        }
        break;
      }

      throw new Error(`SaaS login failed (${lastStatus}): ${lastBody}`);
    };

    const changePassword = async (
      accessToken: string,
      currentPassword: string,
      newPassword: string
    ): Promise<LoginResponse> => {
      const changeResponse = await request.post(
        `${credentials.apiBaseUrl}/v1/auth/change-password`,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
          },
          data: {
            current_password: currentPassword,
            new_password: newPassword,
          },
        }
      );

      if (!changeResponse.ok()) {
        const text = await changeResponse.text();
        throw new Error(`Change password failed (${changeResponse.status()}): ${text}`);
      }

      const payload = (await changeResponse.json()) as LoginResponse;
      if (!payload?.access_token) {
        throw new Error(
          `Password change succeeded but no access_token in response. ` +
          `Status: ${changeResponse.status()}, Body: ${JSON.stringify(payload)}`
        );
      }
      return payload;
    };

    const candidateEmails = SAAS_E2E_EMAIL
      ? [SAAS_E2E_EMAIL]
      : [buildSaasE2eEmail(), buildSaasE2eEmail('recovery')];

    let accessToken: string | null = null;

    for (const email of candidateEmails) {
      const createdUser = await createUser(email);
      if (createdUser) {
        const loginPayload = await loginWithPassword(
          createdUser.email,
          createdUser.temp_password
        );
        let token = loginPayload.access_token;
        const changePayload = await changePassword(
          token,
          createdUser.temp_password,
          SAAS_E2E_PASSWORD
        );
        token = changePayload.access_token;

        accessToken = token;
        break;
      }

      try {
        const existingLogin = await loginWithPassword(email, SAAS_E2E_PASSWORD);
        accessToken = existingLogin.access_token;
        break;
      } catch (error) {
        console.warn('[getSaasAuthHeaders] Login with known password failed:', error);
      }
    }

    if (!accessToken) {
      throw new Error('Unable to obtain SaaS access token for data rights tests.');
    }

    if (typeof accessToken !== 'string' || accessToken.split('.').length !== 3) {
      throw new Error('Invalid JWT format. Expected 3 parts (header.payload.signature).');
    }

    cachedSaasAuthHeaders = {
      Authorization: `Bearer ${accessToken}`,
    };
    return cachedSaasAuthHeaders;
  })();

  try {
    cachedSaasAuthHeaders = await cachedSaasAuthHeadersPromise;
    return cachedSaasAuthHeaders;
  } finally {
    cachedSaasAuthHeadersPromise = null;
  }
}

/**
 * Request a data export for a lead (synchronous admin export).
 * Returns the export bundle immediately.
 */
export async function requestDataExportSync(
  request: APIRequestContext,
  options: { leadId?: string; email?: string }
): Promise<{ response: DataExportResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(`${credentials.apiBaseUrl}/v1/admin/data/export`, {
    headers: {
      ...getAdminAuthHeaders(credentials),
      'Content-Type': 'application/json',
    },
    data: {
      lead_id: options.leadId,
      email: options.email,
    },
  });

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Data export failed (${status}): ${text}`);
    throw new Error(`Data export failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Request a data export (async flow via data-rights endpoint).
 * Returns export request metadata (export_id, status).
 */
export async function requestDataExportAsync(
  request: APIRequestContext,
  options?: { leadId?: string; email?: string }
): Promise<{ response: DataRightsExportRequestResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const saasHeaders = await getSaasAuthHeaders(request);
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/data-rights/export-request`,
    {
      headers: {
        ...saasHeaders,
        'Content-Type': 'application/json',
      },
      data: options ? { lead_id: options.leadId, email: options.email } : {},
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Async export request failed (${status}): ${text}`);
    throw new Error(`Async export request failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * List data export requests for a subject.
 */
export async function listDataExports(
  request: APIRequestContext,
  options?: { leadId?: string; email?: string }
): Promise<{ response: DataRightsExportListResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const saasHeaders = await getSaasAuthHeaders(request);
  const params = new URLSearchParams();
  if (options?.leadId) params.set('lead_id', options.leadId);
  if (options?.email) params.set('email', options.email);

  const url = `${credentials.apiBaseUrl}/v1/data-rights/exports${params.toString() ? `?${params}` : ''}`;
  const response = await request.get(url, {
    headers: saasHeaders,
  });

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`List exports failed (${status}): ${text}`);
    throw new Error(`List exports failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Download a completed data export.
 * Returns the download response or redirect URL.
 */
export async function downloadDataExport(
  request: APIRequestContext,
  exportId: string
): Promise<{ body: Buffer | null; status: number; contentType: string | null }> {
  const credentials = defaultAdminCredentials();
  const saasHeaders = await getSaasAuthHeaders(request);
  const response = await request.get(
    `${credentials.apiBaseUrl}/v1/data-rights/exports/${exportId}/download`,
    {
      headers: saasHeaders,
      maxRedirects: 0,
    }
  );

  const status = response.status();
  const contentType = response.headers()['content-type'] ?? null;

  if (status === 307) {
    // Redirect to signed URL - this is expected for cloud storage
    return { body: null, status, contentType };
  }

  if (!response.ok() && status !== 307) {
    const text = await response.text();
    console.error(`Download export failed (${status}): ${text}`);
    throw new Error(`Download export failed: ${status} - ${text}`);
  }

  const body = await response.body();
  return { body, status, contentType };
}

/**
 * Request data deletion for a lead.
 */
export async function requestDataDeletion(
  request: APIRequestContext,
  options: { leadId?: string; email?: string; reason?: string }
): Promise<{ response: DataDeletionResponse; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/data-deletion/requests`,
    {
      headers: {
        ...getAdminAuthHeaders(credentials),
        'Content-Type': 'application/json',
      },
      data: {
        lead_id: options.leadId,
        email: options.email,
        reason: options.reason,
      },
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Deletion request failed (${status}): ${text}`);
    throw new Error(`Deletion request failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Run retention cleanup (processes pending deletions).
 */
export async function runRetentionCleanup(
  request: APIRequestContext
): Promise<{ response: Record<string, number>; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/retention/cleanup`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Retention cleanup failed (${status}): ${text}`);
    throw new Error(`Retention cleanup failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Trigger processing of pending data exports (test-only endpoint).
 * This should only be available when E2E_TEST_MODE=1.
 */
export async function processDataExports(
  request: APIRequestContext
): Promise<{ response: Record<string, number>; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/test/process-data-exports`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Process exports failed (${status}): ${text}`);
    throw new Error(`Process exports failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Poll for export completion with deterministic retries.
 * Returns the export when completed or throws if max retries exceeded.
 */
export async function waitForExportCompletion(
  request: APIRequestContext,
  exportId: string,
  options?: {
    maxRetries?: number;
    pollIntervalMs?: number;
    leadId?: string;
    email?: string;
  }
): Promise<DataRightsExportListItem> {
  const maxRetries = options?.maxRetries ?? 30;
  const pollIntervalMs = options?.pollIntervalMs ?? 1000;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    // Try to trigger job processing (if test hook is available)
    if (attempt > 0 && attempt % 3 === 0) {
      try {
        await processDataExports(request);
      } catch {
        // Ignore - test hook may not be available
      }
    }

    const { response } = await listDataExports(request, {
      leadId: options?.leadId,
      email: options?.email,
    });

    const exportItem = response.items.find((item) => item.export_id === exportId);
    if (exportItem) {
      if (exportItem.status === 'completed') {
        return exportItem;
      }
      if (exportItem.status === 'failed') {
        throw new Error(`Export ${exportId} failed`);
      }
    }

    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  throw new Error(`Export ${exportId} did not complete within ${maxRetries} attempts`);
}

/**
 * Seed a test lead for data rights testing via the E2E test endpoint.
 */
export async function seedTestLead(
  request: APIRequestContext,
  options?: { email?: string; name?: string }
): Promise<{ leadId: string; email: string }> {
  const credentials = defaultAdminCredentials();
  const testEmail = options?.email ?? buildE2eEmail('e2e-data-rights');
  const testName = options?.name ?? 'E2E Data Rights Test Lead';

  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/test/seed-lead`,
    {
      headers: {
        ...getAdminAuthHeaders(credentials),
        'Content-Type': 'application/json',
      },
      data: {
        name: testName,
        email: testEmail,
        phone: '+15555550199',
      },
    }
  );

  if (!response.ok()) {
    const text = await response.text();
    console.error(`Seed lead failed (${response.status()}): ${text}`);
    throw new Error(`Seed lead failed: ${response.status()} - ${text}`);
  }

  const lead = await response.json();
  return { leadId: lead.lead_id, email: lead.email ?? testEmail };
}

/**
 * Process pending deletions via the E2E test endpoint.
 */
export async function processDeletions(
  request: APIRequestContext
): Promise<{ response: Record<string, number>; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.post(
    `${credentials.apiBaseUrl}/v1/admin/test/process-deletions`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Process deletions failed (${status}): ${text}`);
    throw new Error(`Process deletions failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}

/**
 * Get a lead by ID.
 */
export async function getLead(
  request: APIRequestContext,
  leadId: string
): Promise<{ response: Record<string, unknown> | null; status: number }> {
  const credentials = defaultAdminCredentials();
  const response = await request.get(
    `${credentials.apiBaseUrl}/v1/admin/leads/${leadId}`,
    {
      headers: getAdminAuthHeaders(credentials),
    }
  );

  const status = response.status();
  if (status === 404) {
    return { response: null, status };
  }
  if (!response.ok()) {
    const text = await response.text();
    console.error(`Get lead failed (${status}): ${text}`);
    throw new Error(`Get lead failed: ${status} - ${text}`);
  }

  return { response: await response.json(), status };
}
