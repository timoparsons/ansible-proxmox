#!/bin/bash
# Back up named config files from this Proxmox host:
#   1. optionally as a tar.gz on the site NAS (settings in /etc/host-backup/local.conf)
#   2. to PBS as backup type host
# Paths: /etc/host-backup/paths.list. Secrets are excluded by exclude.list.
# PBS credentials: /etc/host-backup/pbs.env (mode 600, never in git).
set -euo pipefail

CONF=/etc/host-backup
STAGE=$(mktemp -d /var/tmp/host-config.XXXXXX)
NAS_MNT=""
cleanup() {
  if [ -n "$NAS_MNT" ]; then umount "$NAS_MNT" 2>/dev/null || true; rmdir "$NAS_MNT" 2>/dev/null || true; fi
  rm -rf "$STAGE"
}
trap cleanup EXIT

. "$CONF/backup.conf"                 # BACKUP_ID
set -a; . "$CONF/pbs.env"; set +a     # PBS_REPOSITORY, PBS_PASSWORD, PBS_FINGERPRINT
LOCAL_CIFS=""; LOCAL_CREDS=/root/.smbcredentials; LOCAL_KEEP=8
if [ -f "$CONF/local.conf" ]; then . "$CONF/local.conf"; fi
RC=0

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
  sed -i -E "s/((pushover_token|pushover_user|password|secret)[A-Za-z_]* *=[ >]*')[^']*'/\1REDACTED'/I" "$STAGE"/files/var/lib/vz/snippets/*
fi

# 4. add rebuild context
pveversion -v > "$STAGE/files/pveversion.txt" 2>&1 || true
dpkg-query -W > "$STAGE/files/packages.txt" 2>&1 || true
( cd "$STAGE/files" && find . -type f | sort ) > "$STAGE/manifest"
mv "$STAGE/manifest" "$STAGE/files/manifest.txt"

# 5. local copy on the site NAS, independent of PBS and of the network between sites
if [ -n "$LOCAL_CIFS" ]; then
  NAS_MNT=$(mktemp -d /var/tmp/host-config-nas.XXXXXX)
  if mount -t cifs "$LOCAL_CIFS" "$NAS_MNT" -o "credentials=$LOCAL_CREDS,vers=3.0"; then
    OUT="$NAS_MNT/$BACKUP_ID-$(date -u +%Y-%m-%dT%H%M%SZ).tar.gz"
    if tar -C "$STAGE/files" -czf "$OUT" .; then
      echo "local copy written: $(basename "$OUT") ($(du -h "$OUT" | cut -f1))"
      # keep the newest LOCAL_KEEP copies, ordered by name (the names carry the timestamp)
      ls -1 "$NAS_MNT"/"$BACKUP_ID"-*.tar.gz | sort -r | tail -n +"$((LOCAL_KEEP + 1))" | while read -r old; do rm -f "$old"; echo "removed old local copy: $(basename "$old")"; done || true
    else
      echo "ERROR: could not write the local copy" >&2; RC=1
    fi
  else
    echo "ERROR: could not mount $LOCAL_CIFS, local copy skipped" >&2; RC=1
  fi
fi

# 6. upload to PBS
if proxmox-backup-client backup "host-config.pxar:$STAGE/files" --backup-type host --backup-id "$BACKUP_ID" --skip-lost-and-found; then
  echo "PBS upload finished"
else
  echo "ERROR: PBS upload failed" >&2; RC=1
fi
echo "host-config backup finished for $BACKUP_ID (exit code $RC)"
exit $RC
