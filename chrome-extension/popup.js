import { getApiKey, getCachedResearch, setCachedResearch } from './utils/storage.js';
import { createResearch, getResearchStatus } from './utils/api.js';
import { WEB_APP_URL, POLL_INTERVAL_MS, MAX_POLL_ATTEMPTS, EXCLUDED_DOMAINS, EXCLUDED_PROTOCOLS } from './utils/constants.js';

// --- DOM refs ---
const states = {
  noKey: document.getElementById('stateNoKey'),
  loading: document.getElementById('stateLoading'),
  excluded: document.getElementById('stateExcluded'),
  notResearched: document.getElementById('stateNotResearched'),
  researching: document.getElementById('stateResearching'),
  completed: document.getElementById('stateCompleted'),
  error: document.getElementById('stateError'),
};

function showState(name) {
  Object.values(states).forEach(el => el.classList.remove('active'));
  states[name].classList.add('active', 'fade-in');
}

// --- Domain extraction ---
function extractDomain(url) {
  try {
    const parsed = new URL(url);
    if (EXCLUDED_PROTOCOLS.some(p => parsed.protocol.startsWith(p))) return null;
    let host = parsed.hostname.replace(/^www\./, '');
    if (EXCLUDED_DOMAINS.some(d => host === d || host.endsWith(`.${d}`))) return null;
    return host;
  } catch {
    return null;
  }
}

// --- Score rendering ---
function renderCompleted(data) {
  const scores = data.scores || {};
  const setScore = (id, val) => {
    document.getElementById(`score${id}`).textContent = val ?? '—';
    document.getElementById(`bar${id}`).style.width = `${val ?? 0}%`;
  };
  setScore('Composite', scores.composite);
  setScore('Pain', scores.pain);
  setScore('Fit', scores.fit);
  setScore('Timing', scores.timing);

  document.getElementById('summary').textContent = data.summary || '';

  const tpList = document.getElementById('tpList');
  tpList.innerHTML = '';
  (data.talking_points || []).slice(0, 3).forEach(tp => {
    const li = document.createElement('li');
    li.textContent = tp;
    tpList.appendChild(li);
  });

  const docId = data.id || data.doc_id;
  document.getElementById('viewFull').href = `${WEB_APP_URL}/document/${docId}`;

  document.getElementById('copyScores').onclick = () => {
    const text = `Composite: ${scores.composite ?? '—'} | Pain: ${scores.pain ?? '—'} | Fit: ${scores.fit ?? '—'} | Timing: ${scores.timing ?? '—'}`;
    navigator.clipboard.writeText(text);
    const toast = document.getElementById('toast');
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 1500);
  };

  showState('completed');
}

// --- Polling ---
async function pollResearch(jobId, apiKey, domain) {
  const elapsedEl = document.getElementById('elapsed');
  const start = Date.now();
  let attempts = 0;

  const tick = () => { elapsedEl.textContent = `${Math.round((Date.now() - start) / 1000)}s`; };
  const timer = setInterval(tick, 1000);

  try {
    while (attempts < MAX_POLL_ATTEMPTS) {
      attempts++;
      const res = await getResearchStatus(jobId, apiKey);
      if (res.status === 'completed' || res.status === 'complete') {
        clearInterval(timer);
        await setCachedResearch(domain, res);
        renderCompleted(res);
        chrome.runtime.sendMessage({ type: 'BADGE_UPDATE', domain, score: res.scores?.composite });
        return;
      }
      if (res.status === 'failed' || res.status === 'error') {
        clearInterval(timer);
        showError(res.error || 'Research failed.');
        return;
      }
      await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
    }
    clearInterval(timer);
    showError('Research timed out. Please try again.');
  } catch (e) {
    clearInterval(timer);
    showError(e.message);
  }
}

// --- Error handling ---
function showError(msg) {
  const el = document.getElementById('errorMsg');
  const text = typeof msg === 'string' ? msg : (msg?.message || String(msg));
  if (text.includes('402') || text.includes('credits')) {
    el.textContent = 'Insufficient credits. Add credits at auggie.tools/billing.';
  } else if (text.includes('429')) {
    el.textContent = 'Rate limited. Please wait a moment and try again.';
  } else {
    el.textContent = text;
  }
  showState('error');
}

// --- Init ---
let currentDomain = null;

async function init() {
  showState('loading');
  try {
    const apiKey = await getApiKey();
    if (!apiKey) { showState('noKey'); return; }

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const domain = extractDomain(tab?.url || '');
    document.getElementById('headerDomain').textContent = domain || '';

    if (!domain) { showState('excluded'); return; }
    currentDomain = domain;

    const cached = await getCachedResearch(domain);
    if (cached) { renderCompleted(cached); return; }

    document.getElementById('nrDomain').textContent = domain;
    showState('notResearched');
  } catch (e) {
    showError(e);
  }
}

// --- Event listeners ---
document.getElementById('openOptions').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

document.getElementById('startResearch').addEventListener('click', async () => {
  showState('researching');
  try {
    const apiKey = await getApiKey();
    const res = await createResearch(currentDomain, apiKey);
    await pollResearch(res.job_id || res.id, apiKey, currentDomain);
  } catch (e) {
    showError(e.status === 402 ? 'Insufficient credits.' : e);
  }
});

document.getElementById('retryBtn').addEventListener('click', () => {
  init();
});

init();
