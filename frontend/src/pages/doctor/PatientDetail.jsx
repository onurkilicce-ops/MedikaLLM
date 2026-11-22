import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import config from '../../api/config';
import { useDoctorPanel } from './panelContext';
import LoadingScreen from '../../components/LoadingScreen';
import { useT, useLang } from '../../i18n/lang';
import { DOCTOR_STRINGS } from '../../i18n/strings/doctor';

function PatientDetail() {
  const t = useT(DOCTOR_STRINGS);
  const { lang } = useLang();
  const { viewParams, navigateTo } = useDoctorPanel();
  const patientId = viewParams?.patientId;
  const [patient, setPatient] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [interactions, setInteractions] = useState(null);
  const [interactionsLoading, setInteractionsLoading] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [consultations, setConsultations] = useState(null);
  const [consultationsLoading, setConsultationsLoading] = useState(false);

  useEffect(() => {
    if (patientId) loadPatient();
  }, [patientId]);

  useEffect(() => {
    if (activeTab === 'consultations' && !consultations) {
      loadConsultations();
    }
  }, [activeTab]);

  const loadConsultations = async () => {
    setConsultationsLoading(true);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${config.API_URL}/api/conversations/patient/${patientId}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setConsultations(data.conversations || []);
      }
    } catch (err) {
      console.error('Failed to load consultations:', err);
    } finally {
      setConsultationsLoading(false);
    }
  };

  const loadPatient = async () => {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${config.API_URL}/api/users/profile/patient/${patientId}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setPatient(data);
      } else {
        navigateTo('patients');
      }
    } catch (err) {
      console.error('Failed to load patient:', err);
    } finally {
      setLoading(false);
    }
  };

  const runInteractionCheck = async () => {
    if (!patient?.current_medications?.length) return;
    setInteractionsLoading(true);
    // Drop the previous result so a failed re-check cannot show stale data.
    setInteractions(null);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${config.API_URL}/api/drugs/analyze-patient`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ patient_id: patientId }),
      });
      setInteractions(res.ok ? await res.json() : { status: 'error' });
    } catch (err) {
      console.error('Interaction check failed:', err);
      setInteractions({ status: 'error' });
    } finally {
      setInteractionsLoading(false);
    }
  };

  const runAIAnalysis = async () => {
    if (!patient) return;
    setAnalysisLoading(true);
    try {
      const token = localStorage.getItem('token');
      // Create a temporary conversation for this analysis
      const convRes = await fetch(`${config.API_URL}/api/conversations/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ title: t.detail.analysisTitle(patient.name) }),
      });
      const convData = await convRes.json();
      const conversationId = convData.conversation_id;

      const res = await fetch(`${config.API_URL}/api/session/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
          query: t.detail.analysisPrompt(
            patient.chronic_conditions?.join(', ') || (lang === 'tr' ? 'belirtilmemiş' : 'none listed'),
            patient.allergies?.join(', ') || (lang === 'tr' ? 'yok' : 'none'),
            patient.current_medications?.join(', ') || (lang === 'tr' ? 'yok' : 'none'),
          ),
          conversation_id: conversationId,
          patient_id: patientId,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setAnalysis(data.response || data.content || (lang === 'tr' ? 'Analiz oluşturulamadı.' : 'No analysis generated.'));
      }
    } catch (err) {
      console.error('AI Analysis failed:', err);
      setAnalysis(t.detail.analysisFailed);
    } finally {
      setAnalysisLoading(false);
    }
  };

  if (loading) {
    return <LoadingScreen variant="inline" message={t.loading.patient} />;
  }

  if (!patient) {
    return <div className="empty-state"><h3>{t.detail.noProfile}</h3></div>;
  }

  const tabs = [
    { id: 'overview', label: t.detail.tabOverview },
    { id: 'medications', label: t.detail.tabMedications },
    { id: 'consultations', label: t.detail.tabConsultations },
    { id: 'interactions', label: t.detail.tabInteractions },
    { id: 'analysis', label: t.detail.tabAnalysis },
  ];

  return (
    <div className="patient-detail-page">
      {/* Back + Header */}
      <button className="back-link" onClick={() => navigateTo('patients')}>
        {t.detail.back}
      </button>

      <div className="patient-detail-header">
        <div className="patient-detail-avatar">
          {patient.name?.charAt(0).toUpperCase() || '?'}
        </div>
        <div className="patient-detail-info">
          <h1>{patient.name}</h1>
          <p>{patient.gender || t.detail.genderUnknown} • {patient.date_of_birth || t.detail.dobUnknown}</p>
        </div>
        <button className="btn-primary" onClick={() => navigateTo('chat', { patientId })}>
          {t.detail.aiConsult}
        </button>
      </div>

      {/* Tabs */}
      <div className="detail-tabs">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`detail-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="detail-tab-content">
        {activeTab === 'overview' && (
          <div className="overview-grid">
            <div className="overview-card">
              <h3>{t.detail.labelConditions}</h3>
              {patient.chronic_conditions?.length > 0 ? (
                <div className="tag-list">
                  {patient.chronic_conditions.map((c, i) => (
                    <span key={i} className="badge badge-condition">{c}</span>
                  ))}
                </div>
              ) : (
                <p className="text-muted">{t.detail.noConditions}</p>
              )}
            </div>

            <div className="overview-card">
              <h3>{t.detail.labelAllergies}</h3>
              {patient.allergies?.length > 0 ? (
                <div className="tag-list">
                  {patient.allergies.map((a, i) => (
                    <span key={i} className="badge badge-allergy">{a}</span>
                  ))}
                </div>
              ) : (
                <p className="text-muted">{t.detail.noAllergies}</p>
              )}
            </div>

            <div className="overview-card">
              <h3>{t.detail.labelMedications}</h3>
              {patient.current_medications?.length > 0 ? (
                <div className="tag-list">
                  {patient.current_medications.map((m, i) => (
                    <span key={i} className="badge badge-med">{m}</span>
                  ))}
                </div>
              ) : (
                <p className="text-muted">{t.detail.noMedications}</p>
              )}
            </div>

            {patient.notes && (
              <div className="overview-card full-width">
                <h3>{t.detail.labelNotes}</h3>
                <div className="patient-notes-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{patient.notes}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'medications' && (
          <div>
            <div className="overview-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3>{t.detail.activeMedications} ({patient.current_medications?.length || 0})</h3>
              </div>
              {patient.current_medications?.length > 0 ? (
                <div className="med-list">
                  {patient.current_medications.map((med, i) => (
                    <div key={i} className="med-item">
                      <div className="med-icon">💊</div>
                      <div className="med-info">
                        <div className="med-name">{med}</div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted">{t.detail.noMedsList}</p>
              )}
            </div>
          </div>
        )}

        {activeTab === 'consultations' && (
          <div>
            <div className="overview-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3>{t.detail.consultationHistory}</h3>
                <button className="btn-primary" onClick={() => navigateTo('chat', { patientId })}>
                  {t.detail.newConsultation}
                </button>
              </div>

              {consultationsLoading && <p className="text-muted">{t.detail.loadingConsultations}</p>}

              {consultations && consultations.length === 0 && !consultationsLoading && (
                <p className="text-muted">{t.detail.noConsultations}</p>
              )}

              {consultations && consultations.length > 0 && (
                <div className="consultation-list">
                  {consultations.map((conv) => (
                    <div key={conv.conversation_id} className="consultation-item">
                      <div className="consultation-header">
                        <h4>{conv.title || t.detail.untitled}</h4>
                        <span className="consultation-date">
                          {conv.updated_at ? new Date(conv.updated_at).toLocaleDateString(lang === 'tr' ? 'tr-TR' : 'en-US') : ''}
                        </span>
                      </div>
                      <div className="consultation-meta">
                        <span>{t.detail.messagesCount(conv.messages?.length || 0)}</span>
                      </div>
                      {conv.messages?.length > 0 && (
                        <div className="consultation-preview">
                          {conv.messages[conv.messages.length - 1]?.content?.slice(0, 150)}...
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'interactions' && (
          <div>
            <div className="overview-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3>{t.detail.interactionCheckHeading}</h3>
                <button
                  className="btn-primary"
                  onClick={runInteractionCheck}
                  disabled={interactionsLoading || !patient.current_medications?.length}
                >
                  {interactionsLoading ? t.detail.checking : t.detail.runCheck}
                </button>
              </div>

              {!patient.current_medications?.length && (
                <p className="text-muted">{t.detail.noMedsToCheck}</p>
              )}

              {interactions && interactions.status === 'error' && (
                <p className="text-muted" role="alert" style={{ marginTop: '12px', color: '#f87171' }}>
                  {t.detail.checkFailed}
                </p>
              )}

              {interactions && interactions.status !== 'error' && (
                <div className="interaction-results">
                  {interactions.unresolved_medications?.length > 0 && (
                    <p className="text-muted" role="note">
                      {t.detail.notChecked(interactions.unresolved_medications.join(', '))}
                    </p>
                  )}
                  {interactions.not_checked_over_limit?.length > 0 && (
                    <p className="text-muted" role="note">
                      {t.detail.overLimit(interactions.not_checked_over_limit.map(d => d.name).join(', '))}
                    </p>
                  )}
                  {(() => {
                    const approx = (interactions.medication_matches || []).filter(
                      m => !['name', 'brand', 'synonym'].includes(m.match_type),
                    );
                    return approx.length > 0 ? (
                      <p className="text-muted" role="note">
                        {t.detail.approxMatches(approx.map(m => `${m.input} → ${m.name}`).join('; '))}
                      </p>
                    ) : null;
                  })()}

                  {interactions.status === 'unresolved' ? (
                    <p className="text-muted" style={{ marginTop: '12px' }}>{t.detail.nothingChecked}</p>
                  ) : interactions.interactions?.length > 0 ? (
                    <div className="interaction-list">
                      {interactions.interactions.map((inter, i) => (
                        <div key={i} className="interaction-item">
                          <div className="interaction-drugs">
                            <span className="badge badge-med">{inter.drug1_name || inter.drug1}</span>
                            <span className="interaction-arrow">↔</span>
                            <span className="badge badge-med">{inter.drug2_name || inter.drug2}</span>
                          </div>
                          <p className="interaction-desc">{inter.description}</p>
                          <p className="text-muted" style={{ fontSize: '12px' }}>
                            {t.detail.severityNotRated}
                            {inter.source_url && (
                              <> · <a href={inter.source_url} target="_blank" rel="noopener noreferrer">DrugBank ↗</a></>
                            )}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-muted" style={{ marginTop: '12px' }}>
                      {t.detail.noInteractions}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'analysis' && (
          <div>
            <div className="overview-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3>{t.detail.analysisHeading}</h3>
                <button className="btn-primary" onClick={runAIAnalysis} disabled={analysisLoading}>
                  {analysisLoading ? t.detail.analysing : t.detail.generateAnalysis}
                </button>
              </div>

              {analysisLoading && (
                <div className="analysis-loading">
                  <div className="spinner" />
                  <p>{t.detail.analysingMessage}</p>
                </div>
              )}

              {analysis && !analysisLoading && (
                <div className="analysis-result">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis}</ReactMarkdown>
                </div>
              )}

              {!analysis && !analysisLoading && (
                <p className="text-muted">
                  {t.detail.analysisHint}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default PatientDetail;
