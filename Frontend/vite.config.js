import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, process.cwd(), '');
    var defaultBase = mode === 'production' ? '/trading_eng_frontend/' : '/';
    var base = (mode === 'test' ? '/' : env.VITE_APP_BASE_PATH || defaultBase).replace(/\/?$/, '/');
    return { base: base, plugins: [react()], test: { environment: 'jsdom', globals: true, setupFiles: './tests/setup.ts' } };
});
