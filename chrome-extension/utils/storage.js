import { CACHE_TTL_MS } from './constants.js';

export async function getApiKey() {
  const { apiKey } = await chrome.storage.sync.get('apiKey');
  return apiKey || null;
}

export async function setApiKey(key) {
  await chrome.storage.sync.set({ apiKey: key });
}

export async function getCachedResearch(domain) {
  const key = `research_${domain}`;
  const { [key]: entry } = await chrome.storage.local.get(key);
  if (!entry) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    await chrome.storage.local.remove(key);
    return null;
  }
  return entry.data;
}

export async function setCachedResearch(domain, data) {
  const key = `research_${domain}`;
  await chrome.storage.local.set({ [key]: { data, timestamp: Date.now() } });
}
