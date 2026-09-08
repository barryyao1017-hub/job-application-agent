let checking = false;
let contextInvalidated = false;
const attempted = new Set();

function findResumeInput() {
  // SmartRecruiters renders its upload controls inside open shadow roots and
  // distinguishes the required application résumé from the optional parser
  // with a stable data-test attribute.
  const smartRecruitersResume = document
    .querySelector('spl-dropzone[data-test="resume-upload"]')
    ?.shadowRoot?.querySelector('input[type="file"]');
  if (smartRecruitersResume && /jobs\.smartrecruiters\.com$/i.test(location.hostname)) {
    return smartRecruitersResume;
  }

  // Paylocity's initial "Apply with resume" modal renders a second résumé
  // input behind the modal. Target the modal's explicit résumé control so the
  // general matcher does not reject the page as ambiguous.
  const paylocityForceResume = document.querySelector('input[type="file"]#btn-forceResume');
  if (paylocityForceResume && /recruiting\.paylocity\.com$/i.test(location.hostname)) {
    return paylocityForceResume;
  }

  // Ashby exposes its required résumé upload with this stable, explicit ID
  // while also rendering a separate optional autofill input.
  const ashbyResume = document.querySelector('input[type="file"]#_systemfield_resume');
  if (ashbyResume) return ashbyResume;

  const matches = [...document.querySelectorAll('input[type="file"]')].filter((input) => {
    for (let node = input.parentElement; node && node !== document.body; node = node.parentElement) {
      const text = (node.innerText || node.textContent || '').toLowerCase();
      if (/cover\s*letter/.test(text)) return false;
      if (/(resume|r\u00e9sum\u00e9|\bcv\b)/.test(text)) return true;
    }
    return false;
  });
  return matches.length === 1 ? matches[0] : null;
}

function makeFile(base64, fileName) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new File([bytes], fileName, {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
}

function explicitInput(target) {
  let root = document;
  for (const selector of target.shadowHosts || []) {
    const hosts = root.querySelectorAll(selector);
    if (hosts.length !== 1 || !hosts[0].shadowRoot) throw new Error('Shadow host missing or ambiguous');
    root = hosts[0].shadowRoot;
  }
  const inputs = root.querySelectorAll(target.selector);
  if (inputs.length !== 1) throw new Error('Target must match exactly one element');
  const input = inputs[0];
  if (input.tagName !== 'INPUT' || input.type !== 'file' || input.disabled || !input.isConnected) {
    throw new Error('Target is not an enabled file input');
  }
  // Hidden file inputs are normal; the agent identifies their visible upload control.
  return input;
}

async function report(target, status, error) {
  try {
    await chrome.runtime.sendMessage({ type: 'resume-status', requestId: target.requestId, status, error });
  } catch (failure) {
    if (/Extension context invalidated/i.test(failure.message)) contextInvalidated = true;
  }
}

async function check() {
  if (checking || contextInvalidated) return;
  checking = true;
  let target;
  try {
    const response = await chrome.runtime.sendMessage({ type: 'resume-target' });
    target = response?.target;
    if (!target || attempted.has(target.requestId)) return;
    const input = target.selector ? explicitInput(target) : findResumeInput();
    if (!input) { await report(target, 'needs_target', 'No unique automatic résumé field; provide an explicit target'); return; }
    const result = await chrome.runtime.sendMessage({ type: 'resume-field-ready', requestId: target.requestId });
    if (!result?.ok) { await report(target, 'blocked', result?.error || 'Attachment unavailable'); return; }
    attempted.add(target.requestId);
    // Re-resolve after the asynchronous native call. Never attach to a replacement node.
    const current = target.selector ? explicitInput(target) : findResumeInput();
    if (current !== input || !input.isConnected || input.disabled || location.href !== target.url) {
      throw new Error('Page changed before attachment; inspect and queue again');
    }
    const transfer = new DataTransfer();
    transfer.items.add(makeFile(result.base64, result.fileName));
    input.files = transfer.files;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await report(target, 'dispatched'); // Site acceptance must be checked in the live UI.
  } catch (error) {
    if (/Extension context invalidated/i.test(error.message)) contextInvalidated = true;
    if (target) await report(target, 'blocked', error.message);
  } finally {
    checking = false;
  }
}

check();
setInterval(check, 1500);
