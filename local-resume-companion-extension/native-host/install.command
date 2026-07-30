#!/bin/zsh
set -euo pipefail
here="${0:A:h}"
read "extension_id?Paste the Local Resume Companion extension ID: "
if [[ ! "$extension_id" =~ '^[a-p]{32}$' ]]; then
  echo "That does not look like a Chrome extension ID. Nothing was installed."
  exit 1
fi
for target in \
  "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts" \
  "$HOME/Library/Application Support/ResumeUploadBridge/NativeMessagingHosts"; do
  mkdir -p "$target"
  sed "s/EXTENSION_ID/$extension_id/" "$here/com.local_resume_companion.json" > "$target/com.local_resume_companion.json"
done
cc -O2 "$here/resume_native_host.c" -o "$here/resume-native-host"
chmod 700 "$here/resume-native-host"
echo "Native host installed."
