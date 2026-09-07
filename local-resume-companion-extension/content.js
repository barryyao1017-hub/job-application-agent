let attached = false;

function findResumeInput() {
  // Ashby exposes its required résumé upload with this stable, explicit ID
  // while also rendering a separate optional autofill input.
  const ashbyResume = document.querySelector('input[type="file"]#_systemfield_resume');
  if (ashbyResume) return ashbyResume;

  // SmartRecruiters keeps its real résumé uploader inside an open shadow root
  // and exposes a separate optional apply-with-resume/autofill dropzone.
  const smartRecruitersResume = document
    .querySelector('spl-dropzone[data-test="resume-upload"]')
    ?.shadowRoot?.querySelector('input[type="file"]');
  if (smartRecruitersResume) return smartRecruitersResume;

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

async function check() {
  if (attached) return;
  const input = findResumeInput();
  if (!input) return;
  const result = await chrome.runtime.sendMessage({ type: 'resume-field-ready', url: location.href }).catch(() => null);
  if (!result?.ok || !result.base64 || !result.fileName) return;
  const transfer = new DataTransfer();
  transfer.items.add(makeFile(result.base64, result.fileName));
  input.files = transfer.files;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  attached = input.files?.[0]?.name === result.fileName;
  if (attached) chrome.runtime.sendMessage({ type: 'resume-uploaded', url: location.href, fileName: result.fileName });
}

check();
setInterval(check, 1500);
