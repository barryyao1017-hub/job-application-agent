const HOST_NAME = 'com.local_resume_companion';
const inspected = new Map();
const documents = new Map();

function sendNative(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, message, response => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(response);
    });
  });
}

function matches(target, sender) {
  return target.url === sender.url && (!target.selector ||
    (target.tabId === sender.tab.id && target.frameId === sender.frameId));
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!sender.tab?.id) return;
  const key = `${sender.tab.id}:${sender.frameId}`;
  if (message.type === 'resume-status') {
    chrome.storage.session.set({ [key]: { ...message, tabId: sender.tab.id, frameId: sender.frameId, url: sender.url } });
    return;
  }
  if (!['resume-target', 'resume-field-ready'].includes(message.type)) return;
  const reportConnectionError = async error => {
    await chrome.storage.session.set({ [key]: {
      tabId: sender.tab.id, frameId: sender.frameId, documentId: sender.documentId,
      url: sender.url, status: 'blocked', error,
    } });
  };
  (async () => {
    if (message.type === 'resume-target') {
      if (documents.get(key) !== sender.documentId) {
        documents.set(key, sender.documentId);
        await chrome.storage.session.set({ [key]: { tabId: sender.tab.id, frameId: sender.frameId,
          documentId: sender.documentId, url: sender.url, status: 'idle' } });
      }
      const { target, error } = await sendNative({ type: 'peek-attachment' });
      if (error) { await reportConnectionError(error); respond({ error }); return; }
      if (!target || !matches(target, sender)) { inspected.delete(key); respond({ pending: true }); return; }
      inspected.set(key, { target, documentId: sender.documentId });
      respond({ target });
      return;
    }
    const previous = inspected.get(key);
    if (!previous || previous.documentId !== sender.documentId || previous.target.requestId !== message.requestId || !matches(previous.target, sender)) {
      respond({ error: 'Document or target changed; inspect again' });
      return;
    }
    inspected.delete(key);
    const native = await sendNative({ type: 'claim-attachment', requestId: message.requestId,
      url: sender.url, tabId: sender.tab.id, frameId: sender.frameId });
    respond({ ...native, ok: Boolean(native.base64 && native.fileName) });
  })().catch(async error => {
    // A failed peek has no target yet, so the content script cannot report it.
    // Persist the failure here instead of leaving the popup silently idle.
    try { await reportConnectionError(error.message); }
    finally { respond({ error: error.message }); }
  });
  return true;
});

chrome.tabs.onRemoved.addListener(tabId => {
  for (const key of documents.keys()) {
    if (key.startsWith(`${tabId}:`)) { documents.delete(key); inspected.delete(key); chrome.storage.session.remove(key); }
  }
});
