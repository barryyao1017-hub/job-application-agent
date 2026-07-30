# Local Resume Companion

Private local Chrome extension: it attaches only `/Users/jiayiyao/Documents/Jiayi_Yao_resume.docx` to one clearly labeled Resume/CV input on the active application page. It never submits an application or targets Cover Letter.

## Install once

1. In Chrome, open `chrome://extensions`, enable **Developer mode**, then choose **Load unpacked** and select this folder.
2. Copy the extension ID shown by Chrome, then run `native-host/install.command` and paste that ID when prompted.
4. Click the extension icon on a Greenhouse application and choose **Attach approved r\u00e9sum\u00e9**. Chrome will show a debugging-permission notice for the active tab; approve it only when you intend to attach the r\u00e9sum\u00e9.

For autonomous use, the application bot queues one exact target page with `node enqueue-attach.js "APPLICATION_URL"`. When that page contains one clearly labeled Resume/CV upload field, the extension attaches the approved résumé automatically. The instruction is consumed after one use.
