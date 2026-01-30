import { getApiKey, getCachedResearch, setCachedResearch } from './utils/storage.js';
import { getResearchStatus } from './utils/api.js';
import { EXCLUDED_DOMAINS, EXCLUDED_PROTOCOLS, POLL_INTERVAL_MS, MAX_POLL_ATTEMPTS } from './utils/constants.js';

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

function badgeColor(score) {
  if (score >= 80) return '#22c55e';
  if (score >= 60) return '#eab308';
  return '#ef4444';
}

async function updateBadge(tabId, url) {
  const domain = extractDomain(url);
  if (!domain) {
    chrome.action.setBadgeText({ text: '', tabId });
    return;
  }
  const cached = await getCachedResearch(domain);
  if (cached?.scores?.composite != null) {
    const score = cached.scores.composite;
    chrome.action.setBadgeText({ text: String(score), tabId });
    chrome.action.setBadgeBackgroundColor({ color: badgeColor(score), tabId });
  } else {
    chrome.action.setBadgeText({ text: '', tabId });
  }
}

// --- Active jobs: { domain: { jobId, startedAt } } ---
const activeJobs = {};

async function pollJob(domain, jobId) {
  const apiKey = await getApiKey();
  if (!apiKey) return;

  let attempts = 0;
  while (attempts < MAX_POLL_ATTEMPTS) {
    // Check if job was cancelled
    if (!activeJobs[domain] || activeJobs[domain].jobId !== jobId) return;

    attempts++;
    try {
      const res = await getResearchStatus(jobId, apiKey);
      if (res.status === 'completed' || res.status === 'complete') {
        await setCachedResearch(domain, res);
        delete activeJobs[domain];
        // Update badge on all tabs with this domain
        const tabs = await chrome.tabs.query({});
        for (const tab of tabs) {
          if (tab.url && extractDomain(tab.url) === domain) {
            updateBadge(tab.id, tab.url);
          }
        }
        // Notify popup if open
        chrome.runtime.sendMessage({ type: 'JOB_COMPLETE', domain, data: res }).catch(() => {});
        return;
      }
      if (res.status === 'failed' || res.status === 'error') {
        delete activeJobs[domain];
        chrome.runtime.sendMessage({ type: 'JOB_FAILED', domain, error: res.error || 'Research failed.' }).catch(() => {});
        return;
      }
    } catch (e) {
      // Network error — keep trying
      console.warn('Poll error:', e.message);
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
  }

  // Timed out
  delete activeJobs[domain];
  chrome.runtime.sendMessage({ type: 'JOB_FAILED', domain, error: 'Research timed out.' }).catch(() => {});
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url) updateBadge(tabId, changeInfo.url);
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);
  if (tab.url) updateBadge(tabId, tab.url);
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'START_POLL') {
    const { domain, jobId } = msg;
    activeJobs[domain] = { jobId, startedAt: Date.now() };
    pollJob(domain, jobId);
    sendResponse({ ok: true });
  }

  if (msg.type === 'GET_JOB_STATUS') {
    const job = activeJobs[msg.domain];
    sendResponse(job ? { active: true, jobId: job.jobId, startedAt: job.startedAt } : { active: false });
  }

  if (msg.type === 'BADGE_UPDATE') {
    const { domain, score } = msg;
    if (score != null) {
      chrome.tabs.query({}).then(tabs => {
        for (const tab of tabs) {
          if (tab.url && extractDomain(tab.url) === domain) {
            chrome.action.setBadgeText({ text: String(score), tabId: tab.id });
            chrome.action.setBadgeBackgroundColor({ color: badgeColor(score), tabId: tab.id });
          }
        }
      });
    }
  }

  // Return true to keep sendResponse alive for async
  return true;
});
