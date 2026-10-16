# ansible-proxmox

Ansible for the Calliope and Halcyon homelab sites. Replaces the old proxmox-calliope and proxmox-halcyon config repos.
Design and plan: Obsidian, Project - Homelab Ansible Repo.

## How it works

- Working copy: the Ansible LXC (/opt/ansible-proxmox). GitHub is the history and off-site remote, pushed from the LXC with a deploy key.
- Always pass an inventory: ansible-playbook -i inventories/calliope playbooks/maintenance.yml --check --diff
- Host names carry the site prefix (calliope-frigate, halcyon-frigate).
- files/ holds hand-written configs that are deployed from here. Always run with --check --diff first.
- snapshots/ holds small copies of host files where history matters. Added by the snapshot role, never by hand.
- No secrets in this repo. Hosts keep secrets in env files; the repo holds placeholders. No Ansible Vault is used; anything needed to rebuild comes from the password manager.
- Commits are scanned with gitleaks. A failed scan blocks the commit.

After cloning, enable the hook: git config core.hooksPath .githooks (needs gitleaks installed).

## Host config backup to PBS

- Role: roles/proxmox_host_backup. Playbook: playbooks/proxmox-host-backup.yml. A weekly systemd timer (Sun 07:00) on each Proxmox host copies the named files into a staging folder and uploads them to PBS as backup type host.
- Only paths listed in the role defaults (plus host_vars host_backup_paths_extra) are copied. Never add /etc/pve/priv, /root/.ssh or /root/.smbcredentials. NUT upsd.users and upsmon.conf are excluded (exclude.list). Hard-coded credentials in /var/lib/vz/snippets are redacted in the copy.
- Credentials: playbooks/pbs-host-backup-tokens.yml creates the PBS user hostbackup@pbs (DatastoreBackup only) and one token per host, and writes each token straight into /etc/host-backup/pbs.env (mode 600) on that host. Secrets never appear in output or in this repo.
- Run both sites together: ansible-playbook -i inventories/calliope -i inventories/halcyon playbooks/proxmox-host-backup.yml --check --diff
- Per-site settings go in host_vars (host names are unique across sites). Do not put site settings in group_vars for shared group names such as proxmox_hosts: loading both inventories merges those groups.
- Restore one file or the whole archive: load /etc/host-backup/pbs.env, then proxmox-backup-client restore host/ID/TIMESTAMP host-config.pxar SCRATCH_FOLDER. Compare with the live files before copying anything back.

## Pushover credentials

- Host scripts read /etc/pushover.env (root only, mode 600) with PUSHOVER_TOKEN and PUSHOVER_USER. The hookscript check-mounts.pl on the Calliope host does this; it no longer holds the values itself.
- Change them once for both sites: ansible-playbook -i inventories/calliope -i inventories/halcyon playbooks/pushover-token.yml (hidden prompts). It checks the new values with Pushover first, writes /etc/pushover.env on each host and updates the token and user key inside the Proxmox webhook target pushover-webhook. Add -e send_test=true for a test message.
- Not covered: guests and apps (n8n, Home Assistant and others) keep their own copies.

## Local copy on the site NAS (layer 3)

- Set host_backup_local_cifs in the host's host_vars (currently halcyon-proxmox: //10.2.1.10/backup/halcyon/proxmox) to also write a tar.gz of the same staged files to that share on every run. The script mounts it with the host's /root/.smbcredentials, writes the file, and unmounts. The newest 8 copies are kept, ordered by the timestamp in the name.
- It does not depend on PBS or on the network between sites, so a rebuilt Halcyon host can be restored from the local copy alone: tar xzf FILE -C SCRATCH_FOLDER.
- If the NAS cannot be mounted or PBS cannot be reached, the script still attempts the other destination and exits with an error.

## n8n workflow snapshot

- playbooks/snapshot-n8n.yml exports every n8n workflow (inside the n8n container on calliope-n8n), redacts them ON the n8n host with files/snapshot/redact_n8n.py, fetches only the redacted copies into snapshots/n8n/, commits only when something changed (the gitleaks hook scans the commit) and pushes. Run it: ansible-playbook -i inventories/calliope playbooks/snapshot-n8n.yml
- Redacted: user keys, tokens, API keys and bearer values (including ones hard-coded in code nodes), any long mixed letter and digit string, webhook paths and webhook ids, email addresses and Google calendar ids. Dropped: pinned test data, static data, owner details. Credentials are never exported.
- The script stops the run if a suspicious string survives (a tripwire for long mixed strings, 64 character hex and bearer values). Credential type names such as googleCalendarOAuth2Api are allowed.
- It is a history and diff copy, not a restore source. The restore source is the PBS backup of CT 131, which holds the database and the encryption key for stored credentials (/opt/n8n_data/config). Importing the redacted JSON would lose the redacted values.
- A failed scan leaves the files on disk, unstaged, and fails the run. Nothing is pushed.
- Schedule: weekly, Mondays 00:00 NZ, by the n8n workflow Ansible n8n Snapshot Weekly (id KKzzUUKabwD0PXfQ). It logs in to this host over SSH as root, runs this playbook in /opt/ansible-proxmox, and sends a Pushover summary (OK or FAILED, plus whether anything changed). The workflow was repurposed from the old Pull All workflow on 2026-10-17, so the old weekly pull of guest config into the old repos no longer runs.
