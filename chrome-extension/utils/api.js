import { API_BASE_URL } from './constants.js';

async function request(path, key, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  let res;
  try {
    res = await fetch(url, {
      ...options,
      headers: {
        'Authorization': `Bearer ${key}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
  } catch (e) {
    throw new Error(`Network error: could not reach API. Check your connection.`);
  }
  const contentType = res.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    const err = new Error(`Unexpected response from API (${res.status}). The server may be unavailable.`);
    err.status = res.status;
    throw err;
  }
  const body = await res.json();
  if (!res.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map(d => d.msg || JSON.stringify(d)).join('; ')
      : (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
    const err = new Error(detail || `API error ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

export function validateApiKey(key) {
  return request('/ping', key);
}

export function createResearch(domain, key) {
  return request('/research', key, {
    method: 'POST',
    body: JSON.stringify({ company_url: domain }),
  });
}

export function getResearchStatus(jobId, key) {
  return request(`/research/${jobId}`, key);
}

export function generateSequence(docId, key) {
  return request(`/research/${docId}/sequence`, key, { method: 'POST' });
}
