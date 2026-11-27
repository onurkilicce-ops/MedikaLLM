// Live M-02 flow only (vite.m02.config.js): jsdom replaces AbortController,
// but Node's built-in fetch accepts only Node's own AbortSignal and throws
// "Expected signal ... to be an instance of AbortSignal" for jsdom's. A real
// browser has one AbortSignal, so the app code is unchanged; this wrapper
// keeps the page's abort semantics (an aborted request rejects with
// AbortError) without handing the jsdom signal to Node's fetch.
const nativeFetch = globalThis.fetch;

function abortError() {
  return new DOMException('The operation was aborted.', 'AbortError');
}

globalThis.fetch = (input, init = {}) => {
  const { signal, ...rest } = init;
  if (!signal) return nativeFetch(input, rest);
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener('abort', onAbort, { once: true });
    nativeFetch(input, rest).then(resolve, reject)
      .finally(() => signal.removeEventListener('abort', onAbort));
  });
};
