import { getCachedResearch } from './utils/storage.js';
import { EXCLUDED_DOMAINS, EXCLUDED_PROTOCOLS } from './utils/constants.js';

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

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url) updateBadge(tabId, changeInfo.url);
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const tab = await chrome.tabs.get(tabId);
  if (tab.url) updateBadge(tabId, tab.url);
});

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type === 'BADGE_UPDATE' && sender.tab) {
    const score = msg.score;
    if (score != null) {
      chrome.action.setBadgeText({ text: String(score), tabId: sender.tab.id });
      chrome.action.setBadgeBackgroundColor({ color: badgeColor(score), tabId: sender.tab.id });
    }
  }
  if (msg.type === 'CHECK_BADGE') {
    // popup asks for badge refresh — handled by popup itself via cache
  }
});
