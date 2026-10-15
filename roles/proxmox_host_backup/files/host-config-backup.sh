#!/bin/bash
# Back up named config files from this Proxmox host to PBS (backup type host).
# Paths: /etc/host-backup/paths.list. Secrets are excluded by exclude.list.
# PBS credentials: /etc/host-backup/pbs.env (mode 600, never in git).
set -euo pipefail

CONF=/etc/host-backup
STAGE=$(mktemp -d /var/tmp/host-config.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

. "$CONF/backup.conf"                 # BACKUP_ID
set -a; . "$CONF/pbs.env"; set +a     # PBS_REPOSITORY, PBS_PASSWORD, PBS_FINGERPRINT

# 1. keep only listed paths that exist on this host
: > "$STAGE/paths"
while IFS= read -r p; do
  if [ -n "$p" ] && [ -e "$p" ]; then echo "${p#/}" >> "$STAGE/paths"; fi
done < "$CONF/paths.list"

# 2. copy them into a staging folder, structure preserved
mkdir -p "$STAGE/files"
rsync -a --recursive --files-from="$STAGE/paths" --exclude-from="$CONF/exclude.list" / "$STAGE/files/"

# 3. redact hard-coded credentials in the copies (the originals are untouched)
if [ -d "$STAGE/files/var/lib/vz/snippets" ]; then
  sed -i -E "s/((pushover|token|password|secret)[A-Za-z_]* *=[ >]*')[^']*'/\1REDACTED'/I" "$STAGE"/files/var/lib/vz/snippets/*
fi

# 4. add rebuild context
pveversion -v > "$STAGE/files/pveversion.txt" 2>&1 || true
dpkg-query -W > "$STAGE/files/packages.txt" 2>&1 || true
( cd "$STAGE/files" && find . -type f | sort ) > "$STAGE/manifest"
mv "$STAGE/manifest" "$STAGE/files/manifest.txt"

# 5. upload to PBS
proxmox-backup-client backup "host-config.pxar:$STAGE/files" --backup-type host --backup-id "$BACKUP_ID" --skip-lost-and-found
echo "host-config backup finished for $BACKUP_ID"
