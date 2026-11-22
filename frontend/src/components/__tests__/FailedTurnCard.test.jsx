/**
 * Failed chat turn card: never rendered as an answer, raw server text is not
 * shown for unknown codes, and retry is offered only where it can help.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import FailedTurnCard, { describeFailure, formatWait } from '../FailedTurnCard';
import { CHAT_STRINGS } from '../../i18n/strings/chat';

const s = CHAT_STRINGS.tr.streamErrors;

describe('FailedTurnCard', () => {
  test('known code → localised text, partial text collapsed and labelled, retry works', () => {
    const onRetry = vi.fn();
    render(
      <FailedTurnCard
        message={{
          failure: { code: 'llm_unreachable', retryable: true, requestId: 'abc' },
          retryQuery: 'Warfarin + aspirin?',
          partialContent: 'Warfarin increases',
        }}
        strings={s}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(s.codes.llm_unreachable);
    expect(screen.getByText(s.partialSummary)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: s.retry }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test('no retry button when the caller does not allow it (older card / non-retryable)', () => {
    render(
      <FailedTurnCard
        message={{ failure: { code: 'llm_auth', retryable: false }, retryQuery: 'q' }}
        strings={s}
        onRetry={null}
      />,
    );
    expect(screen.queryByRole('button', { name: s.retry })).toBeNull();
    expect(screen.getByRole('alert')).toHaveTextContent(s.notRetryable);
  });

  test('unknown code never shows raw server text', () => {
    const text = describeFailure({ code: 'weird', message: 'psycopg2 password=x' }, s);
    expect(text).toBe(s.generic);
  });
});

describe('FailedTurnCard provider limits', () => {
  test('daily quota → localised text, provider wait shown, no retry button', () => {
    render(
      <FailedTurnCard
        message={{ failure: { code: 'llm_daily_quota', retryable: false, retryAfterSeconds: 433 }, retryQuery: 'q' }}
        strings={s}
        onRetry={null}
      />,
    );
    const card = screen.getByRole('alert');
    expect(card).toHaveTextContent(s.codes.llm_daily_quota);
    expect(card).toHaveTextContent(s.retryAfter('8 dk'));
    expect(screen.queryByRole('button', { name: s.retry })).toBeNull();
  });

  test('formatWait uses seconds, minutes and hours', () => {
    expect(formatWait(34, s.units)).toBe('34 sn');
    expect(formatWait(433, s.units)).toBe('8 dk');
    expect(formatWait(7380, s.units)).toBe('2 sa 3 dk');
    expect(formatWait(7200, s.units)).toBe('2 sa');
    expect(formatWait(null, s.units)).toBeNull();
  });

  test('every backend error code has text in both languages', () => {
    const codes = ['llm_rate_limited', 'llm_daily_quota', 'llm_request_too_large'];
    for (const lang of ['en', 'tr']) {
      for (const code of codes) {
        expect(typeof CHAT_STRINGS[lang].streamErrors.codes[code]).toBe('string');
      }
      expect(typeof CHAT_STRINGS[lang].thinking.providerWait(12)).toBe('string');
    }
  });
});
