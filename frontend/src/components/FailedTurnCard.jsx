import MarkdownWithReferences from './MarkdownWithReferences';

/**
 * Text for a failed assistant turn. Known codes come from the backend
 * (src/session/stream_errors.py) or the client stream reader
 * (src/api/chatStream.js); anything else falls back to a generic message so
 * raw server text is never shown.
 */
export function describeFailure(failure, strings) {
  if (!failure) return strings.generic;
  if (failure.code === 'http_error') return strings.codes.http_error(failure.httpStatus ?? '?');
  if (failure.code === 'quota' && failure.message) return failure.message; // localised by the caller
  const known = strings.codes[failure.code];
  return typeof known === 'string' ? known : strings.generic;
}

/** Provider-requested wait (seconds) as "45 s", "8 min", "2 h 5 min". */
export function formatWait(seconds, units) {
  const s = Math.ceil(Number(seconds));
  if (!Number.isFinite(s) || s <= 0 || !units) return null;
  if (s < 60) return `${s} ${units.seconds}`;
  if (s < 3600) return `${Math.ceil(s / 60)} ${units.minutes}`;
  const hours = Math.floor(s / 3600);
  const minutes = Math.ceil((s % 3600) / 60);
  return minutes ? `${hours} ${units.hours} ${minutes} ${units.minutes}` : `${hours} ${units.hours}`;
}

/**
 * Rendered instead of an answer when a chat turn did not complete. The
 * interrupted partial text (if any) stays collapsed and labelled, so it is
 * never mistaken for an answer, and the same question can be retried.
 */
export default function FailedTurnCard({ message, strings, onRetry, retryDisabled }) {
  const failure = message.failure || {};
  const wait = strings.retryAfter ? formatWait(failure.retryAfterSeconds, strings.units) : null;
  return (
    <div className="failed-turn" role="alert" data-testid="failed-turn">
      <div className="failed-turn-title">⚠️ {strings.title}</div>
      <p className="failed-turn-text">{describeFailure(failure, strings)}</p>
      {wait && <p className="failed-turn-meta">{strings.retryAfter(wait)}</p>}
      {failure.retryable === false && (
        <p className="failed-turn-meta">{strings.notRetryable}</p>
      )}
      {failure.requestId && <p className="failed-turn-meta">{strings.requestId(failure.requestId)}</p>}
      {message.partialContent ? (
        <details className="failed-turn-partial">
          <summary>{strings.partialSummary}</summary>
          <MarkdownWithReferences
            content={message.partialContent}
            sources={message.partialSources || []}
            onSourceClick={() => {}}
          />
        </details>
      ) : null}
      {message.retryQuery && onRetry ? (
        <button type="button" className="failed-turn-retry" onClick={onRetry} disabled={retryDisabled}>
          {strings.retry}
        </button>
      ) : null}
    </div>
  );
}
