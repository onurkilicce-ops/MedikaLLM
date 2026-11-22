/**
 * Chat SSE stream handling, kept free of React so it can be unit tested.
 *
 * The previous inline parser in Chat.jsx threw inside the JSON-parse
 * try/catch when an `error` event arrived, so the error was logged as a
 * "parse failure" and swallowed: an error-only stream ended as
 * "No response received" and partial text followed by an error was stored
 * as a normal, successful answer. Here every stream ends in exactly one
 * explicit outcome and only `complete` may be shown as an answer.
 */

export const STREAM_OUTCOME = Object.freeze({
  COMPLETE: 'complete', // `done` received with non-empty content
  EMPTY: 'empty', // `done` received but the answer is empty
  ERROR: 'error', // backend sent an `error` event
  INTERRUPTED: 'interrupted', // connection closed before `done`/`error`
  TIMEOUT: 'timeout', // no data for longer than the idle timeout
  ABORTED: 'aborted', // cancelled locally (e.g. user navigated away)
});

/** Default: the backend sends a heartbeat at least every ~15 s. */
export const DEFAULT_IDLE_TIMEOUT_MS = 60000;

const MALFORMED = '__malformed__';

/**
 * Incremental SSE parser. `feed()` accepts arbitrary text fragments (events
 * may be split anywhere, including inside a JSON payload or a CRLF pair) and
 * returns the complete events parsed so far; `flush()` parses a trailing
 * event that was not terminated by a blank line.
 */
export function createSseParser() {
  let buffer = '';

  const parseBlock = (block) => {
    const dataLines = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).replace(/^ /, ''));
      }
      // Lines starting with ':' are comments (heartbeats); `event:`/`id:`
      // fields are not used by this backend and are ignored.
    }
    if (dataLines.length === 0) return null;
    try {
      const parsed = JSON.parse(dataLines.join('\n'));
      if (parsed && typeof parsed === 'object') return parsed;
      return { type: MALFORMED };
    } catch {
      return { type: MALFORMED };
    }
  };

  const normalise = (text) => {
    let combined = buffer + text;
    // Keep a trailing CR until the next fragment: it may be half of CRLF.
    const trailingCR = combined.endsWith('\r');
    if (trailingCR) combined = combined.slice(0, -1);
    combined = combined.replace(/\r\n|\r/g, '\n');
    return trailingCR ? `${combined}\r` : combined;
  };

  return {
    feed(text) {
      buffer = normalise(text);
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() ?? '';
      return blocks.map(parseBlock).filter(Boolean);
    },
    flush() {
      const rest = buffer.replace(/\r$/, '');
      buffer = '';
      if (!rest.trim()) return [];
      const event = parseBlock(rest);
      return event ? [event] : [];
    },
  };
}

export function createStreamState() {
  return {
    content: '',
    sources: [],
    toolExecutions: [],
    debug: {},
    citationCheck: null,
    persisted: true, // false when the backend could not save the answer
    thinking: null, // { kind: 'status', text } | { kind: 'tool', tool } | null
    // Transient provider notice, e.g. { code: 'provider_rate_limit_wait',
    // retryAfterSeconds, limit }: the provider asked for a wait before the
    // client retries. Cleared as soon as the answer makes progress again.
    notice: null,
    done: false,
    error: null, // { code, message, retryable, requestId, retryAfterSeconds }
    malformedEvents: 0,
  };
}

const NOTICE_CODES = new Set(['provider_rate_limit_wait']);

function positiveSeconds(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.ceil(n) : null;
}

function mergeSources(existing, incoming) {
  if (!Array.isArray(incoming) || incoming.length === 0) return existing;
  const byRef = new Map();
  for (const s of existing) byRef.set(s?.ref ?? JSON.stringify(s), s);
  for (const s of incoming) byRef.set(s?.ref ?? JSON.stringify(s), s);
  return Array.from(byRef.values());
}

/** Pure reducer: returns the next state for one parsed SSE event. */
export function applyStreamEvent(state, event) {
  if (!event || typeof event !== 'object') return state;
  // `error` and `done` are terminal; anything after them is ignored so a
  // late chunk can never turn a failed stream back into an answer.
  if (state.error || state.done) return state;

  switch (event.type) {
    case 'thinking':
      return { ...state, notice: null, thinking: { kind: 'status', text: String(event.step || '') } };
    case 'tool_start':
      return { ...state, notice: null, thinking: { kind: 'tool', tool: event.tool_name || 'unknown' } };
    case 'tool_end':
      return { ...state, notice: null, thinking: null };
    case 'content':
      if (typeof event.content !== 'string' || event.content === '') return state;
      return { ...state, notice: null, thinking: null, content: state.content + event.content };
    case 'sources':
      return { ...state, sources: mergeSources(state.sources, event.sources) };
    case 'status':
      // Unknown status codes are ignored (forward compatible).
      if (!NOTICE_CODES.has(event.code)) return state;
      return {
        ...state,
        notice: {
          code: event.code,
          retryAfterSeconds: positiveSeconds(event.retry_after_seconds),
          limit: typeof event.limit === 'string' ? event.limit : null,
        },
      };
    case 'heartbeat':
      return state;
    case 'done': {
      const finalContent =
        typeof event.final_content === 'string' && event.final_content.trim()
          ? event.final_content
          : state.content;
      return {
        ...state,
        done: true,
        thinking: null,
        notice: null,
        content: finalContent,
        sources: Array.isArray(event.sources) ? event.sources : state.sources,
        toolExecutions: Array.isArray(event.tool_executions) ? event.tool_executions : [],
        debug: { execution_time_ms: event.execution_time_ms, debug: event.debug },
        citationCheck: event.citation_check || null,
        persisted: event.persisted !== false,
      };
    }
    case 'error':
      return {
        ...state,
        thinking: null,
        notice: null,
        error: {
          code: typeof event.code === 'string' && event.code ? event.code : 'unknown_error',
          message:
            typeof event.message === 'string'
              ? event.message
              : typeof event.error === 'string'
                ? event.error
                : '',
          retryable: event.retryable !== false,
          requestId: event.request_id || null,
          retryAfterSeconds: positiveSeconds(event.retry_after_seconds),
        },
      };
    case MALFORMED:
      return { ...state, malformedEvents: state.malformedEvents + 1 };
    default:
      return state;
  }
}

/**
 * Turn the final stream state into an outcome. `endReason` is why reading
 * stopped: 'eof' (server closed), 'timeout', 'aborted' or 'read_error'.
 */
export function finalizeStream(state, endReason = 'eof') {
  const base = {
    content: state.content,
    sources: state.sources,
    toolExecutions: state.toolExecutions,
    debug: state.debug,
    citationCheck: state.citationCheck,
    persisted: state.persisted,
    malformedEvents: state.malformedEvents,
  };
  if (state.error) {
    return { ...base, outcome: STREAM_OUTCOME.ERROR, error: state.error, partialContent: state.content };
  }
  if (state.done) {
    if (state.content && state.content.trim()) {
      return { ...base, outcome: STREAM_OUTCOME.COMPLETE, error: null, partialContent: '' };
    }
    return {
      ...base,
      outcome: STREAM_OUTCOME.EMPTY,
      error: { code: 'empty_response', message: '', retryable: true, requestId: null },
      partialContent: '',
    };
  }
  const outcome =
    endReason === 'timeout'
      ? STREAM_OUTCOME.TIMEOUT
      : endReason === 'aborted'
        ? STREAM_OUTCOME.ABORTED
        : STREAM_OUTCOME.INTERRUPTED;
  return {
    ...base,
    outcome,
    error: { code: `stream_${outcome}`, message: '', retryable: true, requestId: null },
    partialContent: state.content,
  };
}

const TIMED_OUT = Symbol('timed-out');

async function readWithTimeout(reader, ms) {
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(TIMED_OUT), ms);
  });
  try {
    return await Promise.race([reader.read(), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Read a chat SSE response body to the end.
 *
 * @param {ReadableStreamDefaultReader} reader  response.body.getReader()
 * @param {object} options
 * @param {(state) => void} [options.onUpdate]  called after every event
 * @param {number} [options.idleTimeoutMs]      max silence before giving up
 * @param {AbortSignal} [options.signal]        local cancellation
 * @returns {Promise<object>} finalizeStream() result
 */
export async function consumeChatStream(reader, options = {}) {
  const { onUpdate, idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS, signal } = options;
  const decoder = new TextDecoder();
  const parser = createSseParser();
  let state = createStreamState();
  let endReason = 'eof';

  const apply = (events) => {
    for (const event of events) {
      const next = applyStreamEvent(state, event);
      if (next !== state) {
        state = next;
        if (onUpdate) onUpdate(state);
      }
    }
  };

  try {
    // Stop reading once a terminal event arrived: whatever follows cannot
    // change the outcome, and an open connection must not keep the UI busy.
    while (!state.error && !state.done) {
      if (signal?.aborted) {
        endReason = 'aborted';
        break;
      }
      let result;
      try {
        result = await readWithTimeout(reader, idleTimeoutMs);
      } catch {
        endReason = signal?.aborted ? 'aborted' : 'read_error';
        break;
      }
      if (result === TIMED_OUT) {
        endReason = 'timeout';
        break;
      }
      if (result.done) {
        apply(parser.feed(decoder.decode()));
        apply(parser.flush());
        endReason = 'eof';
        break;
      }
      apply(parser.feed(decoder.decode(result.value, { stream: true })));
    }
  } finally {
    if (state.error || state.done || endReason !== 'eof') {
      try {
        await reader.cancel();
      } catch {
        /* reader already closed */
      }
    }
    try {
      reader.releaseLock();
    } catch {
      /* lock already released */
    }
  }
  return finalizeStream(state, endReason);
}

/**
 * Prepare a retry of a failed assistant turn: drop the failed message (and
 * nothing else) so the original user message stays in place and the same
 * query can be sent again without duplicating it in the thread.
 */
export function removeFailedTurn(messages, failedIndex) {
  if (!Array.isArray(messages)) return { messages: [], query: null };
  const failed = messages[failedIndex];
  if (!failed || failed.role !== 'assistant' || failed.status !== 'failed') {
    return { messages, query: null };
  }
  return {
    messages: messages.filter((_, i) => i !== failedIndex),
    query: failed.retryQuery || null,
  };
}
