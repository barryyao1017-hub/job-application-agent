const status = document.querySelector('#status');
document.querySelector('#attach').disabled = true;
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
const entries = Object.values(await chrome.storage.session.get(null)).filter(item => item.tabId === tab?.id);
status.textContent = entries.length ? entries.map(item =>
  `Tab ${item.tabId}, frame ${item.frameId}\n${item.url}\n${item.status}${item.error ? ': ' + item.error : ''}`
).join('\n\n') : 'No attachment helper is active on this page. Refresh the application page after reloading the extension.';
