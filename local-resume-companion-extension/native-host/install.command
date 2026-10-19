#!/bin/zsh
set -euo pipefail
here="${0:A:h}"
root="${here:h:h}"
config="${root}/config.json"
if [[ ! -f "$config" ]]; then
  echo "Missing config.json. Copy config.example.json to config.json and set approved_resume_path."
  exit 1
fi
resume_path="$(node -e 'const c=require(process.argv[1]); if (!c.approved_resume_path) process.exit(1); process.stdout.write(c.approved_resume_path)' "$config")"
if [[ ! -r "$resume_path" ]]; then
  echo "The configured approved_resume_path does not exist or is not readable."
  exit 1
fi
read "extension_id?Paste the Local Resume Companion extension ID: "
if [[ ! "$extension_id" =~ '^[a-p]{32}$' ]]; then
  echo "That does not look like a Chrome extension ID. Nothing was installed."
  exit 1
fi
for target in \
  "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts" \
  "$HOME/Library/Application Support/ResumeUploadBridge/NativeMessagingHosts"; do
  mkdir -p "$target"
  sed -e "s/EXTENSION_ID/$extension_id/" -e "s|NATIVE_HOST_PATH|$here/resume-native-host|" "$here/com.local_resume_companion.json" > "$target/com.local_resume_companion.json"
done
python3 - "$here" <<'PYTHON'
import json, pathlib, subprocess, sys
here = pathlib.Path(sys.argv[1])
subprocess.run(['/usr/bin/clang', '-fobjc-arc', '-framework', 'Foundation',
                '-DRESUME_ROOT=' + json.dumps(str(here.parent.parent)),
                str(here / 'resume_native_host.m'), '-o', str(here / 'resume-native-host')], check=True)
subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--identifier',
                'com.local_resume_companion.host', str(here / 'resume-native-host')], check=True)
PYTHON
chmod 700 "$here/resume-native-host"
echo "Native host installed."
