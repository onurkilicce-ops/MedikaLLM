import { mergeConfig } from 'vite';
import base from './vite.config';

// Opt-in real API/PG flow; not collected by the ordinary offline UI suite.
export default mergeConfig(base, { test: { include:['e2e/*.flow.jsx'], testTimeout:20000,
  hookTimeout:20000, fileParallelism:false } });
