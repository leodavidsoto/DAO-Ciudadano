import { defineConfig, devices } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { E2E_FIXTURE } from './tests/support/e2e-fixture.js';

const e2eDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryDirectory = resolve(e2eDirectory, '..');
const frontendPort = Number(process.env.E2E_FRONTEND_PORT || 3005);
const frontendUrl = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
    testDir: './tests',
    outputDir: './test-results',
    fullyParallel: false,
    forbidOnly: Boolean(process.env.CI),
    retries: process.env.CI ? 1 : 0,
    workers: 1,
    timeout: 180_000,
    expect: { timeout: 30_000 },
    reporter: [
        ['list'],
        ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ],
    use: {
        baseURL: frontendUrl,
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',
    },
    webServer: {
        // Use the package lifecycle so `prestart` verifies and syncs the
        // canonical circuit artifacts into the ignored public/zk directory.
        // Calling craco directly makes a clean checkout depend on stale local
        // assets and can silently test a different proving key.
        command: 'npm start',
        cwd: resolve(repositoryDirectory, 'frontend'),
        url: frontendUrl,
        // Never attach to a developer's server: CRA bakes REACT_APP_* at
        // startup, so reusing a stale process can silently select another
        // issuer or deployment manifest.
        reuseExistingServer: false,
        timeout: 180_000,
        env: {
            ...process.env,
            BROWSER: 'none',
            HOST: '127.0.0.1',
            PORT: String(frontendPort),
            REACT_APP_BACKEND_URL: frontendUrl,
            REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS: E2E_FIXTURE.issuerAddress,
            REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS: E2E_FIXTURE.membershipContract,
            REACT_APP_MACI_COORDINATOR_ADDRESS: E2E_FIXTURE.maciCoordinator,
            REACT_APP_MACI_TALLY_VERIFIER_ADDRESS: E2E_FIXTURE.maciTallyVerifier,
        },
    },
    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
    ],
});
