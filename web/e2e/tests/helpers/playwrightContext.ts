import type { Page, TestInfo } from '@playwright/test';

type ContextWithBaseUrlOptions = {
  page: Page;
  testInfo: TestInfo;
};

export async function newContextWithBaseUrl({
  page,
  testInfo,
}: ContextWithBaseUrlOptions) {
  const baseURL =
    typeof testInfo.project.use?.baseURL === 'string'
      ? testInfo.project.use.baseURL
      : undefined;

  const browser = page.context().browser();
  if (!browser) {
    throw new Error('Expected an available browser to create a new context.');
  }

  return browser.newContext({ baseURL });
}
