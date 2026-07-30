const HOST_NAME = 'com.local_resume_companion';

function sendNative(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, message, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else resolve(response);
    });
  });
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.type !== 'resume-field-ready' || !sender.tab?.id) return;
  (async () => {
    const native = await sendNative({ type: 'claim-attachment', url: message.url });
    if (!native?.base64 || !native?.fileName) {
      respond({ ok: false, pending: true, error: native?.error });
      return;
    }
    // The content script owns the DOM in its own frame.  Passing bytes back to
    // that script avoids debugger frame IDs entirely, including cross-origin
    // Greenhouse iframes.
    respond({ ok: true, base64: native.base64, fileName: native.fileName });
  })().catch((error) => respond({ ok: false, error: error.message }));
  return true;
});
