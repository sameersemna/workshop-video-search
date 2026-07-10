import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./src/tests/setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      thresholds: {
        lines: Number(process.env.FRONTEND_COVERAGE_LINES_MIN ?? '0'),
        functions: Number(process.env.FRONTEND_COVERAGE_FUNCTIONS_MIN ?? '1'),
        branches: Number(process.env.FRONTEND_COVERAGE_BRANCHES_MIN ?? '1'),
        statements: Number(process.env.FRONTEND_COVERAGE_STATEMENTS_MIN ?? '0'),
      },
    },
  },
});