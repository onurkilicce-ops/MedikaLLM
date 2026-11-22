import { useState, useEffect, useRef } from 'react';
import config from '../api/config';
import { useT } from '../i18n/lang';
import { DRUG_MATRIX_STRINGS } from '../i18n/strings/drugMatrix';
import { CELL, cellState, selectionKey, summarize } from './drugMatrixModel';
import './DrugMatrix.css';

// Neutral styling per cell state. There is deliberately no severity scale:
// DrugBank's interaction records carry no severity label and the former
// text-pattern score was not a clinical rating. "No record" is grey, not
// green — absence of a record is not evidence of safety.
const CELL_STYLE = {
  [CELL.RECORD]: { color: '#f59e0b', bg: 'rgba(245,158,11,0.16)' },
  [CELL.NO_RECORD]: { color: '#9ca3af', bg: 'transparent' },
  [CELL.NOT_CHECKED]: { color: '#a78bfa', bg: 'rgba(167,139,250,0.10)' },
  [CELL.ERROR]: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  [CELL.LOADING]: { color: '#9ca3af', bg: 'transparent' },
};

// One interaction check covers at most 10 drugs (backend request limit).
const MAX_DRUGS = 10;

/**
 * DrugMatrix — embeddable view for the Chat page.
 *
 * No layout chrome (no `.app`, no header, no theme toggle). The host page
 * is responsible for placement and theming. Pass `user` so the component
 * can decide whether to expose patient-load options (doctors only).
 */
function DrugMatrix({ user, initialPatientId = null }) {
  const t = useT(DRUG_MATRIX_STRINGS);

  const [drugs, setDrugs] = useState([]); // [{drug_id, name}]
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  // Interaction result bound to the selection it was computed for:
  // { key, phase: 'loading' | 'done' | 'error', data }
  const [result, setResult] = useState(null);
  const [selectedCell, setSelectedCell] = useState(null);
  const [patients, setPatients] = useState([]);
  const [selectedPatient, setSelectedPatient] = useState('');
  // Patient medication names that could not be matched to a database drug,
  // names whose lookup failed, and matched drugs beyond the 10-drug limit.
  const [unmatchedMeds, setUnmatchedMeds] = useState([]);
  const [failedMeds, setFailedMeds] = useState([]);
  const [overLimitMeds, setOverLimitMeds] = useState([]);
  const searchTimer = useRef(null);
  const inFlight = useRef(null);
  const patientLoadSeq = useRef(0);
  const currentKey = selectionKey(drugs.map(d => d.drug_id));

  // Load patients for quick-load feature (doctors only) and optionally
  // hydrate the matrix from a patient passed in by the host.
  useEffect(() => {
    if (!user) return;
    if (user.isDoctor) loadPatients();
    if (initialPatientId) loadPatientMeds(initialPatientId);
  }, [user, initialPatientId]);

  const loadPatients = async () => {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${config.API_URL}/api/users/doctors/patients`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setPatients(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to load patients:', err);
    }
  };

  const loadPatientMeds = async (patientId) => {
    // Only the most recent patient selection may write the drug list.
    const seq = ++patientLoadSeq.current;
    const isCurrent = () => seq === patientLoadSeq.current;
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${config.API_URL}/api/users/profile/patient/${patientId}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        if (!isCurrent()) return;
        setSelectedPatient(patientId);
        setUnmatchedMeds([]);
        setFailedMeds([]);
        setOverLimitMeds([]);
        if (data.current_medications?.length > 0) {
          // Resolve medication names → drug IDs. Names that cannot be
          // matched (or whose lookup fails) are listed, not silently dropped.
          const resolved = [];
          const unmatched = [];
          const failed = [];
          for (const medName of data.current_medications) {
            try {
              const searchRes = await fetch(`${config.API_URL}/api/drugs/search/${encodeURIComponent(medName)}?limit=1`, {
                headers: { 'Authorization': `Bearer ${token}` },
              });
              const body = searchRes.ok ? await searchRes.json() : null;
              if (!body || body.success === false) {
                failed.push(medName); // lookup failed: unknown, not "no match"
                continue;
              }
              const results = body.results || [];
              if (results.length > 0) {
                if (!resolved.some(d => d.drug_id === results[0].drug_id)) {
                  resolved.push({ drug_id: results[0].drug_id, name: results[0].name });
                }
              } else {
                unmatched.push(medName);
              }
            } catch {
              failed.push(medName);
            }
          }
          if (!isCurrent()) return;
          setDrugs(resolved.slice(0, MAX_DRUGS));
          setOverLimitMeds(resolved.slice(MAX_DRUGS).map(d => d.name));
          setUnmatchedMeds(unmatched);
          setFailedMeds(failed);
        }
      }
    } catch (err) {
      console.error('Failed to load patient medications:', err);
    }
  };

  // Debounced drug search
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const q = searchQuery.trim();
    if (q.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      try {
        const token = localStorage.getItem('token');
        const res = await fetch(`${config.API_URL}/api/drugs/search/${encodeURIComponent(q)}?limit=8`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          const results = data.results || data;
          setSearchResults(results.filter(d => !drugs.some(existing => existing.drug_id === d.drug_id)));
        }
      } catch (err) {
        console.error('Search failed:', err);
      } finally {
        setSearching(false);
      }
    }, 300);
  }, [searchQuery, drugs]);

  // Re-check interactions whenever the drug list changes. The previous
  // result is replaced immediately by a loading state for the new selection,
  // the previous request is aborted, and a late response for an old
  // selection is ignored.
  useEffect(() => {
    setSelectedCell(null);
    if (drugs.length < 2) {
      if (inFlight.current) inFlight.current.abort();
      setResult(null);
      return;
    }
    checkInteractions(drugs.map(d => d.drug_id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drugs]);

  useEffect(() => () => inFlight.current?.abort(), []);

  const checkInteractions = async (drugIds) => {
    const key = selectionKey(drugIds);
    if (inFlight.current) inFlight.current.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setResult({ key, phase: 'loading', data: null });
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${config.API_URL}/api/drugs/interactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ drug_ids: drugIds }),
        signal: controller.signal,
      });
      const data = res.ok ? await res.json() : null;
      if (controller.signal.aborted) return;
      setResult(res.ok ? { key, phase: 'done', data } : { key, phase: 'error', data: null });
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error('Interaction check failed:', err);
      setResult({ key, phase: 'error', data: null });
    }
  };

  const addDrug = (drug) => {
    if (drugs.length >= MAX_DRUGS) {
      setSearchQuery('');
      setSearchResults([]);
      return;
    }
    if (!drugs.some(d => d.drug_id === drug.drug_id)) {
      setDrugs([...drugs, { drug_id: drug.drug_id, name: drug.name }]);
    }
    setSearchQuery('');
    setSearchResults([]);
  };

  const removeDrug = (drugId) => {
    setDrugs(drugs.filter(d => d.drug_id !== drugId));
    setSelectedCell(null);
  };

  const summary = summarize(result, currentKey, drugs);
  const isLoading = drugs.length >= 2 && (!result || result.key !== currentKey || result.phase === 'loading');
  const hasError = Boolean(result && result.key === currentKey &&
    (result.phase === 'error' || result.data?.status === 'error'));
  const cellLabel = {
    [CELL.RECORD]: t.cell.record,
    [CELL.NO_RECORD]: t.cell.noRecord,
    [CELL.NOT_CHECKED]: t.cell.notChecked,
    [CELL.ERROR]: t.cell.error,
    [CELL.LOADING]: t.cell.loading,
  };

  return (
    <div className="drug-matrix-page" style={{ padding: '24px 32px', overflowY: 'auto', height: '100%' }}>
      <div className="page-header">
        <h1>{t.title}</h1>
        <p>{t.subtitle}</p>
      </div>

      {/* Drug Input Section */}
      <div className="matrix-controls">
        <div className="matrix-search-section">
          <div className="matrix-search-box">
            <input
              type="text"
              placeholder={t.searchPlaceholder}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="matrix-search-input"
            />
            {searching && <span className="search-spinner" />}
            {searchResults.length > 0 && (
              <div className="matrix-search-dropdown">
                {searchResults.map(drug => (
                  <button
                    key={drug.drug_id}
                    className="matrix-search-result"
                    onClick={() => addDrug(drug)}
                  >
                    <span className="drug-result-name">{drug.name}</span>
                    <span className="drug-result-id">{drug.drug_id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {patients.length > 0 && (
            <div className="matrix-patient-select">
              <select
                value={selectedPatient}
                onChange={(e) => {
                  if (e.target.value) loadPatientMeds(e.target.value);
                }}
              >
                <option value="">{t.loadFromPatient}</option>
                {patients.map(p => (
                  <option key={p.patient_id} value={p.patient_id}>
                    {p.name} ({t.patientMedsHint(p.current_medications?.length || 0)})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {drugs.length > 0 && (
          <div className="matrix-drug-chips">
            {drugs.map(drug => (
              <span key={drug.drug_id} className="drug-chip">
                {drug.name}
                <button onClick={() => removeDrug(drug.drug_id)} className="chip-remove">×</button>
              </span>
            ))}
            {drugs.length > 0 && (
              <button className="chip-clear-all" onClick={() => { setDrugs([]); setSelectedCell(null); setUnmatchedMeds([]); setFailedMeds([]); setOverLimitMeds([]); }}>
                {t.clearAll}
              </button>
            )}
          </div>
        )}
      </div>

      {unmatchedMeds.length > 0 && (
        <div className="matrix-notice matrix-notice-warning" role="note">
          {t.patientMedsUnresolved(unmatchedMeds.join(', '))}
        </div>
      )}
      {failedMeds.length > 0 && (
        <div className="matrix-notice matrix-notice-error" role="note">
          {t.patientMedsLookupFailed(failedMeds.join(', '))}
        </div>
      )}
      {overLimitMeds.length > 0 && (
        <div className="matrix-notice matrix-notice-warning" role="note">
          {t.patientMedsOverLimit(overLimitMeds.join(', '))}
        </div>
      )}
      {drugs.length >= MAX_DRUGS && (
        <div className="matrix-notice matrix-notice-warning" role="note">{t.maxDrugs(MAX_DRUGS)}</div>
      )}

      {/* Interaction Matrix */}
      {drugs.length >= 2 && (
        <div className="matrix-container">
          {isLoading && <div className="matrix-loading">{t.checking}</div>}
          {hasError && (
            <div className="matrix-notice matrix-notice-error" role="alert">
              {t.errorBanner}{' '}
              <button type="button" className="matrix-retry" onClick={() => checkInteractions(drugs.map(d => d.drug_id))}>
                {t.retry}
              </button>
            </div>
          )}
          {summary.unresolvedNames.length > 0 && (
            <div className="matrix-notice matrix-notice-warning" role="note">
              {t.unresolvedBanner(summary.unresolvedNames.join(', '))}
            </div>
          )}
          <div className="matrix-grid-wrapper">
            <table className="interaction-matrix">
              <thead>
                <tr>
                  <th className="matrix-corner"></th>
                  {drugs.map(drug => (
                    <th key={drug.drug_id} className="matrix-header-cell">
                      <span className="matrix-header-label">{drug.name}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {drugs.map((rowDrug, rowIdx) => (
                  <tr key={rowDrug.drug_id}>
                    <td className="matrix-row-header">{rowDrug.name}</td>
                    {drugs.map((colDrug, colIdx) => {
                      if (rowIdx === colIdx) {
                        return <td key={colDrug.drug_id} className="matrix-cell diagonal">—</td>;
                      }
                      if (colIdx < rowIdx) {
                        return <td key={colDrug.drug_id} className="matrix-cell mirror"></td>;
                      }
                      const cell = cellState(result, currentKey, rowDrug.drug_id, colDrug.drug_id);
                      const style = CELL_STYLE[cell.state];
                      const inter = cell.state === CELL.RECORD ? cell.interaction : null;
                      const isSelected = selectedCell?.drug1 === rowDrug.drug_id && selectedCell?.drug2 === colDrug.drug_id;
                      return (
                        <td
                          key={colDrug.drug_id}
                          data-cell-state={cell.state}
                          className={`matrix-cell ${inter ? 'has-interaction' : 'no-interaction'} ${isSelected ? 'selected' : ''}`}
                          style={{ backgroundColor: style.bg, borderColor: style.color }}
                          title={t.legend[cell.state] || ''}
                          onClick={() => inter && setSelectedCell({ drug1: rowDrug.drug_id, drug2: colDrug.drug_id, interaction: inter })}
                        >
                          <span className="cell-severity" style={{ color: style.color }}>{cellLabel[cell.state]}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="matrix-summary">
            <div className="summary-stat">
              <span className="summary-value">{drugs.length}</span>
              <span className="summary-label">{t.summaryDrugs}</span>
            </div>
            <div className="summary-stat">
              <span className="summary-value">{summary.records ?? '—'}</span>
              <span className="summary-label">{t.summaryRecords}</span>
            </div>
            <div className="summary-stat">
              <span className="summary-value">
                {summary.pairsChecked != null ? `${summary.pairsChecked}/${summary.pairsTotal}` : '—'}
              </span>
              <span className="summary-label">{t.summaryPairs}</span>
            </div>
          </div>
          <p className="matrix-severity-note">{t.severityNote}</p>
        </div>
      )}

      {drugs.length < 2 && (
        <div className="matrix-empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
          <h3>{t.emptyTitle}</h3>
          <p>{user?.isDoctor ? t.emptyDescDoctor : t.emptyDescGeneric}</p>
        </div>
      )}

      {selectedCell && (
        <div className="interaction-detail-panel">
          <div className="detail-panel-header">
            <h3>
              <span className="badge badge-med">{selectedCell.interaction.drug1_name}</span>
              <span className="interaction-arrow">↔</span>
              <span className="badge badge-med">{selectedCell.interaction.drug2_name}</span>
            </h3>
            <button className="detail-close" onClick={() => setSelectedCell(null)}>×</button>
          </div>
          <div className="detail-panel-body">
            <div className="detail-severity-badge" style={{
              color: CELL_STYLE[CELL.RECORD].color,
              background: CELL_STYLE[CELL.RECORD].bg,
            }}>
              {t.detailSeverity}
            </div>
            <p className="detail-description">{selectedCell.interaction.description}</p>
            {selectedCell.interaction.source_url && (
              <a className="detail-source-link" href={selectedCell.interaction.source_url} target="_blank" rel="noopener noreferrer">
                {t.detailSource}
              </a>
            )}
          </div>
        </div>
      )}

      {/* Severity legend lives at the bottom of the page so it doesn't
          intercept the eye on first load — users only need it when
          interpreting cell colours, which they do AFTER scanning the
          matrix or sample data. Keeping it last also means the legend
          appears under the empty-state hero, not above it. */}
      <div className="matrix-legend matrix-legend-footer">
        <span className="legend-title">{t.legendHeading}:</span>
        {[CELL.RECORD, CELL.NO_RECORD, CELL.NOT_CHECKED, CELL.ERROR].map(state => (
          <span key={state} className="legend-item">
            <span className="legend-dot" style={{ background: CELL_STYLE[state].color }}></span>
            {t.legend[state]}
          </span>
        ))}
      </div>
    </div>
  );
}

export default DrugMatrix;
