import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 240_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.FRONTEND_URL ?? 'http://127.0.0.1:56556',
    headless: true,
    viewport: { width: 1440, height: 960 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'bun run start --port 56556',
    url: 'http://127.0.0.1:56556',
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
