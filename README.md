# ansible-proxmox

Ansible for the Calliope and Halcyon homelab sites. Replaces the old proxmox-calliope and proxmox-halcyon config repos.
Design and plan: Obsidian, Project - Homelab Ansible Repo.

## How it works

- Working copy: the Ansible LXC (/opt/ansible-proxmox). GitHub is the history and off-site remote, pushed from the LXC with a deploy key.
- Always pass an inventory: ansible-playbook -i inventories/calliope playbooks/maintenance.yml --check --diff
- Host names carry the site prefix (calliope-frigate, halcyon-frigate).
- files/ holds hand-written configs that are deployed from here. Always run with --check --diff first.
- snapshots/ holds small copies of host files where history matters. Added by the snapshot role, never by hand.
- No secrets in this repo. Hosts keep secrets in env files; the repo holds placeholders. Rebuild secrets go in Ansible Vault.
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
