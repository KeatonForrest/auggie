export const API_BASE_URL = 'https://auggie.tools/v1';
export const WEB_APP_URL = 'https://auggie.tools';
export const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours
export const POLL_INTERVAL_MS = 3000;
export const MAX_POLL_ATTEMPTS = 200; // 10 min timeout

export const EXCLUDED_DOMAINS = [
  'google.com',
  'linkedin.com',
  'twitter.com',
  'x.com',
  'facebook.com',
  'github.com',
  'youtube.com',
  'reddit.com',
  'wikipedia.org',
  'localhost',
  '127.0.0.1',
];

export const EXCLUDED_PROTOCOLS = ['chrome:', 'about:', 'edge:', 'chrome-extension:'];
