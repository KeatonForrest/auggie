import { getApiKey, setApiKey } from './utils/storage.js';
import { validateApiKey } from './utils/api.js';

const input = document.getElementById('apiKey');
const saveBtn = document.getElementById('saveBtn');
const testBtn = document.getElementById('testBtn');
const status = document.getElementById('status');

function showStatus(msg, ok) {
  status.textContent = msg;
  status.className = `status ${ok ? 'status-ok' : 'status-err'}`;
  status.classList.remove('hidden');
}

async function testKey(key) {
  if (!key || !key.startsWith('sk_live_')) {
    showStatus('Key must start with sk_live_', false);
    return false;
  }
  try {
    await validateApiKey(key);
    showStatus('Connected successfully.', true);
    return true;
  } catch (e) {
    showStatus(e.status === 401 ? 'Invalid API key.' : `Connection failed: ${e.message}`, false);
    return false;
  }
}

saveBtn.addEventListener('click', async () => {
  const key = input.value.trim();
  if (await testKey(key)) {
    await setApiKey(key);
    showStatus('Saved and verified.', true);
  }
});

testBtn.addEventListener('click', () => testKey(input.value.trim()));

// Load existing key
getApiKey().then(key => { if (key) input.value = key; });
