import { defineConfig } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000';

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL,
    // Disable video and trace to avoid ffmpeg dependency when using PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
    // Use system Chrome in CI (via PW_CHANNEL=chrome env var)
    channel: process.env.PW_CHANNEL as 'chrome' | undefined,
    headless: true,
    launchOptions: {
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    },
  },
});
