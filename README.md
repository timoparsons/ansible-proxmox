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
