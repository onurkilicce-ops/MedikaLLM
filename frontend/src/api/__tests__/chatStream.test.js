/**
 * Chat SSE outcome tests.
 *
 * Every scenario feeds raw SSE bytes through the real parser + reducer +
 * reader loop (consumeChatStream) and asserts the single outcome the UI acts
 * on. A failing stream must never come out as `complete`, and must never
 * collapse into an anonymous "No response received".
 */
import { describe, expect, test, vi } from 'vitest';
import {
  STREAM_OUTCOME,
  applyStreamEvent,
  consumeChatStream,
  createSseParser,
  createStreamState,
  removeFailedTurn,
} from '../chatStream';

const sse = (obj) => `data: ${JSON.stringify(obj)}\n\n`;

function fakeReader(chunks, { hangAfter = false, failAt = -1 } = {}) {
  const enc = new TextEncoder();
  let i = 0;
  let cancelled = false;
  return {
    read: vi.fn(() => {
      if (cancelled) return Promise.resolve({ done: true, value: undefined });
      if (i === failAt) {
        i += 1;
        return Promise.reject(new TypeError('network error'));
      }
      if (i < chunks.length) {
        const value = enc.encode(chunks[i]);
        i += 1;
        return Promise.resolve({ done: false, value });
      }
      if (hangAfter) return new Promise(() => {});
      return Promise.resolve({ done: true, value: undefined });
    }),
    cancel: vi.fn(() => {
      cancelled = true;
      return Promise.resolve();
    }),
    releaseLock: vi.fn(),
  };
}

const SRC = { ref: 'REF1', source: 'DrugBank Interaction', title: 'Interaction: Warfarin ↔ Aspirin' };

describe('consumeChatStream outcomes', () => {
  test('normal content + done → complete, final content and sources kept', async () => {
    const reader = fakeReader([
      sse({ type: 'thinking', step: 'Processing your query...' }),
      sse({ type: 'content', content: 'Warfarin and aspirin ' }),
      sse({ type: 'content', content: 'have a documented interaction [1].' }),
      sse({ type: 'sources', sources: [SRC] }),
      sse({
        type: 'done',
        final_content: 'Warfarin and aspirin have a documented interaction [1].',
        sources: [SRC],
        tool_executions: [{ tool_name: 'check_drug_interactions' }],
        citation_check: { cited_refs: [1], unknown_refs: [] },
      }),
    ]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.COMPLETE);
    expect(result.content).toBe('Warfarin and aspirin have a documented interaction [1].');
    expect(result.sources).toEqual([SRC]);
    expect(result.citationCheck.unknown_refs).toEqual([]);
    expect(result.error).toBeNull();
  });

  test('error-only stream → error outcome with code, not an empty answer', async () => {
    const reader = fakeReader([
      sse({ type: 'thinking', step: 'Processing your query...' }),
      sse({
        type: 'error',
        code: 'llm_auth',
        message: 'The language model provider rejected the configured credentials.',
        retryable: false,
        request_id: 'abc123',
      }),
    ]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.ERROR);
    expect(result.error).toMatchObject({ code: 'llm_auth', retryable: false, requestId: 'abc123' });
    expect(result.content).toBe('');
    expect(reader.cancel).toHaveBeenCalled();
  });

  test('partial content then error → error outcome; partial text is not an answer', async () => {
    const reader = fakeReader([
      sse({ type: 'content', content: 'Warfarin increases the risk of' }),
      sse({ type: 'error', code: 'llm_unreachable', message: 'Could not reach the language model provider.', retryable: true }),
      // A late chunk after the terminal error must be ignored.
      sse({ type: 'content', content: ' nothing.' }),
      sse({ type: 'done', final_content: 'should be ignored' }),
    ]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.ERROR);
    expect(result.partialContent).toBe('Warfarin increases the risk of');
    expect(result.error.code).toBe('llm_unreachable');
  });

  test('done with empty final content → empty outcome (explicit, retryable)', async () => {
    const reader = fakeReader([sse({ type: 'done', final_content: '', sources: [] })]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.EMPTY);
    expect(result.error).toMatchObject({ code: 'empty_response', retryable: true });
  });

  test('connection closed without done → interrupted, partial kept separately', async () => {
    const reader = fakeReader([sse({ type: 'content', content: 'Partial answer' })]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.INTERRUPTED);
    expect(result.partialContent).toBe('Partial answer');
    expect(result.error.code).toBe('stream_interrupted');
  });

  test('fragmented events (split JSON, CRLF across chunks, unterminated tail) → complete', async () => {
    const done = JSON.stringify({ type: 'done', final_content: 'Final [1].', sources: [SRC] });
    const reader = fakeReader([
      'data: {"type":"cont',
      'ent","content":"Fin"}\r',
      '\n\r\ndata: {"type":"content","content":"al [1]."}\n\ndata: {"type":"sou',
      `rces","sources":[${JSON.stringify(SRC)}]}\n\n`,
      `data: ${done}`, // no trailing blank line before EOF
    ]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.COMPLETE);
    expect(result.content).toBe('Final [1].');
    expect(result.malformedEvents).toBe(0);
  });

  test('malformed event is counted, heartbeats ignored, stream still completes', async () => {
    const reader = fakeReader([
      ': keep-alive\n\n',
      'data: {not json}\n\n',
      sse({ type: 'heartbeat' }),
      sse({ type: 'content', content: 'Answer' }),
      sse({ type: 'done', final_content: 'Answer' }),
    ]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.COMPLETE);
    expect(result.malformedEvents).toBe(1);
  });

  test('silent connection → timeout outcome and the reader is cancelled', async () => {
    const reader = fakeReader([sse({ type: 'content', content: 'Half' })], { hangAfter: true });
    const result = await consumeChatStream(reader, { idleTimeoutMs: 30 });
    expect(result.outcome).toBe(STREAM_OUTCOME.TIMEOUT);
    expect(result.partialContent).toBe('Half');
    expect(reader.cancel).toHaveBeenCalled();
  });

  test('network read failure → interrupted', async () => {
    const reader = fakeReader([sse({ type: 'content', content: 'x' })], { failAt: 1 });
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.INTERRUPTED);
  });

  test('legacy error payload without code still ends as error', async () => {
    const reader = fakeReader([sse({ type: 'error', error: 'Streaming error' })]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.ERROR);
    expect(result.error.code).toBe('unknown_error');
  });

  test('sources arriving mid-stream are visible before done', async () => {
    const seen = [];
    const reader = fakeReader([
      sse({ type: 'sources', sources: [SRC] }),
      sse({ type: 'content', content: 'Cited [1]' }),
      sse({ type: 'done', final_content: 'Cited [1]', sources: [SRC] }),
    ]);
    await consumeChatStream(reader, { onUpdate: (s) => seen.push(s) });
    const beforeDone = seen.filter((s) => !s.done);
    expect(beforeDone.some((s) => s.sources.length === 1 && s.content === 'Cited [1]')).toBe(true);
  });
});

describe('retry after failure', () => {
  test('failed turn is removed and the same query can be streamed again', async () => {
    const messages = [
      { role: 'user', content: 'Warfarin + aspirin?' },
      { role: 'assistant', status: 'failed', retryQuery: 'Warfarin + aspirin?', failure: { code: 'llm_timeout' } },
    ];
    const { messages: kept, query } = removeFailedTurn(messages, 1);
    expect(kept).toEqual([{ role: 'user', content: 'Warfarin + aspirin?' }]);
    expect(query).toBe('Warfarin + aspirin?');

    const first = await consumeChatStream(fakeReader([sse({ type: 'error', code: 'llm_timeout', message: 'x' })]));
    expect(first.outcome).toBe(STREAM_OUTCOME.ERROR);
    const second = await consumeChatStream(
      fakeReader([sse({ type: 'content', content: 'Answer' }), sse({ type: 'done', final_content: 'Answer' })]),
    );
    expect(second.outcome).toBe(STREAM_OUTCOME.COMPLETE);
  });

  test('a successful message is never removed as a failed turn', () => {
    const messages = [
      { role: 'user', content: 'q' },
      { role: 'assistant', content: 'a' },
    ];
    expect(removeFailedTurn(messages, 1)).toEqual({ messages, query: null });
  });
});

describe('parser and reducer units', () => {
  test('parser keeps an incomplete event buffered until its terminator arrives', () => {
    const parser = createSseParser();
    expect(parser.feed('data: {"type":"content","content":"a"}')).toEqual([]);
    expect(parser.feed('\n\n')).toEqual([{ type: 'content', content: 'a' }]);
  });

  test('reducer ignores content after done', () => {
    let s = createStreamState();
    s = applyStreamEvent(s, { type: 'done', final_content: 'A' });
    const after = applyStreamEvent(s, { type: 'content', content: 'B' });
    expect(after).toBe(s);
  });
});

describe('provider wait notice (status events)', () => {
  test('a rate-limit wait shows a notice that clears when the answer resumes', async () => {
    const notices = [];
    const reader = fakeReader([
      sse({ type: 'tool_end', tool_name: 'get_drug_info' }),
      sse({ type: 'status', code: 'provider_rate_limit_wait', retry_after_seconds: 33.4, limit: 'tpm', request_id: 'r1' }),
      sse({ type: 'content', content: 'Warfarin is an anticoagulant [1].' }),
      sse({ type: 'done', final_content: 'Warfarin is an anticoagulant [1].', sources: [SRC] }),
    ]);
    const result = await consumeChatStream(reader, { onUpdate: (s) => notices.push(s.notice) });
    expect(notices).toContainEqual({ code: 'provider_rate_limit_wait', retryAfterSeconds: 34, limit: 'tpm' });
    expect(notices[notices.length - 1]).toBeNull();
    expect(result.outcome).toBe(STREAM_OUTCOME.COMPLETE);
  });

  test('unknown status codes are ignored and a notice never outlives a terminal event', () => {
    let s = applyStreamEvent(createStreamState(), { type: 'status', code: 'something_new' });
    expect(s.notice).toBeNull();
    s = applyStreamEvent(s, { type: 'status', code: 'provider_rate_limit_wait', retry_after_seconds: 5 });
    expect(s.notice).toMatchObject({ retryAfterSeconds: 5 });
    s = applyStreamEvent(s, { type: 'error', code: 'llm_rate_limited', retryable: true });
    expect(s.notice).toBeNull();
    expect(applyStreamEvent(s, { type: 'status', code: 'provider_rate_limit_wait' })).toBe(s);
  });

  test('a daily-quota error keeps the provider wait for the failure card', async () => {
    const reader = fakeReader([
      sse({ type: 'error', code: 'llm_daily_quota', message: 'Daily limit.', retryable: false, retry_after_seconds: 433, request_id: 'r2' }),
    ]);
    const result = await consumeChatStream(reader);
    expect(result.outcome).toBe(STREAM_OUTCOME.ERROR);
    expect(result.error).toMatchObject({ code: 'llm_daily_quota', retryable: false, retryAfterSeconds: 433 });
  });
});
