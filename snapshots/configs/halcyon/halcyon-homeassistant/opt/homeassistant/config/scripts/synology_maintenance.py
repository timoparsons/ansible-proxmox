#!/usr/bin/env python3
"""Hyper Backup throttle control for Home Assistant (Halcyon).

Controls the tc throttle on the Halcyon NAS (/usr/local/bin/hb-throttle) over SSH.
The SSH key is limited, in the NAS's authorized_keys, to the wrapper
/usr/local/bin/hb-throttle-ssh, which accepts only the words status, on and off.
The wrapper runs "sudo -n hb-throttle on|off", allowed for that one command by
/etc/sudoers.d/hb-throttle on the NAS. (DSM 7.1's Task Scheduler API cannot start
tasks, which is why this does not go through DSM.)

Usage:
  synology_maintenance.py halcyon throttle_status
  synology_maintenance.py halcyon throttle_on | throttle_off

Prints a JSON status object on success. On failure prints the reason to stderr
and exits 1, so the Home Assistant sensor goes unknown and the error is logged.
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

ACTIONS = ("throttle_status", "throttle_on", "throttle_off")

THROTTLE_SSH = {
    "halcyon": {
        "host": "10.2.1.10", "port": "26", "user": "tim",
        "key": REDACTED
    },
}


class ThrottleError(Exception):
    pass


def _ssh(nas, word):
    # Send one of the words the NAS wrapper accepts and return its output.
    cfg = THROTTLE_SSH.get(nas)
    if not cfg:
        raise ThrottleError("no throttle control set up for %s" % nas)
    cmd = ["ssh", "-i", cfg["key"], "-p", cfg["port"], "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
           "-o", "ConnectTimeout=8", "-o", "UserKnownHostsFile=%s" % cfg["known_hosts"],
           "-o", "StrictHostKeyChecking=yes", "%s@%s" % (cfg["user"], cfg["host"]), word]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if p.returncode != 0:
        raise ThrottleError("throttle '%s' over ssh failed: %s" % (word, p.stderr.strip() or "ssh exit %d" % p.returncode))
    return p.stdout


def parse_state(out):
    devices = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("on", "off"):
            devices[parts[0]] = (parts[2] if len(parts) > 2 else "on") if parts[1] == "on" else "off"
    if not devices:
        raise ThrottleError("unexpected throttle status output: %r" % out[:200])
    active = {d: r for d, r in devices.items() if r != "off"}
    return {
        "throttle": "on" if active else "off",
        "throttle_rate": next(iter(active.values())) if active else None,
        "throttle_devices": devices,
        "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def throttle_state(nas):
    # Read-only: asks the NAS which interfaces carry the throttle.
    return parse_state(_ssh(nas, "status"))


def throttle(nas, action):
    if action == "throttle_status":
        return throttle_state(nas)
    want = "on" if action == "throttle_on" else "off"
    _ssh(nas, want)
    state = None
    for _ in range(6):  # read the real state back, tc changes apply at once but allow a moment
        state = throttle_state(nas)
        if state["throttle"] == want:
            break
        time.sleep(1)
    state["acted_on"] = ["throttle %s" % want]
    if state["throttle"] != want:
        raise ThrottleError("asked the NAS to turn the throttle %s but it still reads '%s'" % (want, state["throttle"]))
    return state


def main(argv):
    if len(argv) < 3 or argv[1] not in THROTTLE_SSH or argv[2] not in ACTIONS:
        raise ThrottleError("usage: %s <%s> <%s>" % (argv[0], "|".join(THROTTLE_SSH), "|".join(ACTIONS)))
    result = throttle(argv[1], argv[2])
    result["nas"] = argv[1]
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main(sys.argv)
    except ThrottleError as e:
        print("synology_maintenance: %s" % e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # ssh timeout, missing key file
        print("synology_maintenance: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        sys.exit(1)
