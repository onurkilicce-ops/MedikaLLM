import { mergeConfig } from 'vite';
import base from './vite.config';

// Opt-in real API/PG flow; not collected by the ordinary offline UI suite.
// e2e/setup.js bridges jsdom's AbortSignal to Node's fetch (test-only).
export default mergeConfig(base, { test: { include:['e2e/*.flow.jsx'], setupFiles:['./e2e/setup.js'],
  testTimeout:20000, hookTimeout:20000, fileParallelism:false } });
