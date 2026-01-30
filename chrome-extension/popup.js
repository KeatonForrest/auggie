import { getApiKey, getCachedResearch } from './utils/storage.js';
import { createResearch } from './utils/api.js';
import { WEB_APP_URL, EXCLUDED_DOMAINS, EXCLUDED_PROTOCOLS } from './utils/constants.js';

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

  const docId = data.id || data.doc_id || data.document_id;
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

// --- Show researching state with elapsed timer + background check ---
function showResearching(startedAt) {
  showState('researching');
  const elapsedEl = document.getElementById('elapsed');
  const tick = () => { elapsedEl.textContent = `${Math.round((Date.now() - startedAt) / 1000)}s`; };
  tick();
  if (showResearching._timer) clearInterval(showResearching._timer);
  if (showResearching._checker) clearInterval(showResearching._checker);
  showResearching._timer = setInterval(tick, 1000);

  // Periodically check if background job is still active
  showResearching._checker = setInterval(async () => {
    const status = await chrome.runtime.sendMessage({ type: 'GET_JOB_STATUS', domain: currentDomain });
    if (!status?.active) {
      clearInterval(showResearching._timer);
      clearInterval(showResearching._checker);
      // Job ended — check cache for results
      const cached = await getCachedResearch(currentDomain);
      if (cached) {
        renderCompleted(cached);
      } else {
        showError('Research timed out or failed. Please try again.');
      }
    }
  }, 5000);
}

// --- Error handling ---
function showError(msg) {
  console.error('showError called with:', msg);
  const el = document.getElementById('errorMsg');
  const text = typeof msg === 'string' ? msg
    : (msg instanceof Error) ? msg.message
    : (msg?.message || msg?.detail || JSON.stringify(msg));
  if (text.includes('402') || text.includes('credits')) {
    el.textContent = 'Insufficient credits. Add credits at auggie.tools/billing.';
  } else if (text.includes('429')) {
    el.textContent = 'Rate limited. Please wait a moment and try again.';
  } else {
    el.textContent = text;
  }
  showState('error');
}

// --- Progress rendering ---
const PROGRESS_STAGES = ['scraping', 'analyzing', 'enriching', 'generating'];

function updateProgress(stage) {
  const steps = document.querySelectorAll('#progressSteps .step');
  const idx = PROGRESS_STAGES.indexOf(stage);
  steps.forEach((el, i) => {
    el.classList.remove('done', 'active');
    if (i < idx) el.classList.add('done');
    else if (i === idx) el.classList.add('active');
  });
}

// --- Listen for background job updates ---
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'JOB_COMPLETE' && msg.domain === currentDomain) {
    if (showResearching._timer) clearInterval(showResearching._timer);
    renderCompleted(msg.data);
  }
  if (msg.type === 'JOB_FAILED' && msg.domain === currentDomain) {
    if (showResearching._timer) clearInterval(showResearching._timer);
    showError(msg.error);
  }
  if (msg.type === 'JOB_PROGRESS' && msg.domain === currentDomain) {
    updateProgress(msg.progress);
  }
});

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

    // Check cache first
    const cached = await getCachedResearch(domain);
    if (cached) { renderCompleted(cached); return; }

    // Check if background is already polling for this domain
    const jobStatus = await chrome.runtime.sendMessage({ type: 'GET_JOB_STATUS', domain });
    if (jobStatus?.active) {
      showResearching(jobStatus.startedAt);
      return;
    }

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
  try {
    const apiKey = await getApiKey();
    const res = await createResearch(currentDomain, apiKey);
    const jobId = res.job_id || res.id;
    // Hand off polling to background service worker
    await chrome.runtime.sendMessage({ type: 'START_POLL', domain: currentDomain, jobId });
    showResearching(Date.now());
  } catch (e) {
    showError(e.status === 402 ? 'Insufficient credits.' : e);
  }
});

document.getElementById('retryBtn').addEventListener('click', () => {
  init();
});

init();
