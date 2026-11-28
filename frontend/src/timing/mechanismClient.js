import config from '../api/config';

// M-03 lives under /api/mechanism; same Bearer token and error contract as M-02.
export async function mechanismRequest(drug_ids, signal) {
  const response = await fetch(`${config.API_URL}/api/mechanism/compare`, {
    method: 'POST', signal,
    headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ drug_ids }),
  });
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
