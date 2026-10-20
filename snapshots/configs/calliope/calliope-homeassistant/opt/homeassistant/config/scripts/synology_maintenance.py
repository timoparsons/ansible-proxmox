#!/usr/bin/env python3
"""Synology maintenance control for Home Assistant.

Reports and pauses/resumes DSM data scrubbing and Universal Search (SynoFinder)
file indexing, using the same DSM web API calls Storage Manager and Universal
Search make themselves. Logs in as the local-api DSM account for each run.

Usage:
  synology_maintenance.py <nas> status
  synology_maintenance.py <nas> pause_scrub | resume_scrub
  synology_maintenance.py <nas> pause_index [hours]   (hours: 1, 3, 6, or 0 = until resumed)
  synology_maintenance.py <nas> resume_index
  synology_maintenance.py <nas> backup_status                (Hyper Backup tasks and their state)
  synology_maintenance.py <nas> pause_backup <task_id>       (suspend a Hyper Backup task)
  synology_maintenance.py <nas> resume_backup <task_id>      (resume a suspended Hyper Backup task)
  synology_maintenance.py <nas> fingerprint            (print the NAS's certificate fingerprint)
  synology_maintenance.py <nas> throttle_status        (is the Hyper Backup throttle active on each interface?)
  synology_maintenance.py <nas> throttle_on | throttle_off   (run the root DSM tasks that call hb-throttle)

Prints a JSON status object on success. On failure prints the reason to stderr
and exits 1, so the Home Assistant sensor goes unknown and the error is logged.
"""
import hashlib
import http.client
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

# HTTPS with certificate pinning. The NASes use Synology's self-signed certificate, which
# normal verification rejects, so instead the script only talks to a NAS presenting the
# exact certificate whose SHA-256 fingerprint is pinned here. When DSM renews or replaces
# its certificate (Calliope's current one expires 2027-06-28), logins stop with a
# "certificate changed" error showing the new fingerprint; confirm it in DSM
# (Control Panel > Security > Certificate) before pasting it in. To get a fingerprint
# for a new NAS, run:  synology_maintenance.py <nas> fingerprint
NAS = {
    "calliope": {
        "host": "10.1.1.10", "port": 5501,
        "sha256": "REDACTED-LONG",
    },
    "norwich": {"host": "10.1.1.13", "port": 5501, "sha256": None},  # not set up yet
}
ACCOUNT = "local-api"
SECRET_KEY = REDACTED
SECRETS_FILE = REDACTED
SESSION = "HAMaintenance"
TIMEOUT = 20
INDEX_PAUSE_HOURS = (0, 1, 3, 6)  # the options Universal Search itself offers

BACKUP_ACTIONS = ("pause_backup", "resume_backup", "backup_status")
THROTTLE_ACTIONS = ("throttle_status", "throttle_on", "throttle_off")
ACTIONS = ("status", "pause_scrub", "resume_scrub", "pause_index", "resume_index", "fingerprint") + BACKUP_ACTIONS + THROTTLE_ACTIONS

# Hyper Backup throttle (tc rules applied by /usr/local/bin/hb-throttle on Calliope, which needs
# root). DSM Task Scheduler holds two disabled, never-scheduled root tasks that call it; this
# script runs them through the DSM API. State is read back over SSH with a dedicated key that
# is limited, in Calliope's authorized_keys, to one read-only status script.
THROTTLE_TASKS = {"throttle_on": 8, "throttle_off": 9}   # DSM Task Scheduler ids
THROTTLE_SSH = {
    "calliope": {
        "host": "10.1.1.10", "port": "26", "user": "tim",
        "key": REDACTED
    },
}


class DSMError(Exception):
    pass


def REDACTED:
    with open(SECRETS_FILE, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml

        value = yaml.safe_load(text).get(SECRET_KEY)
    except Exception:
        m = re.search(r"^%s:\s*(.+?)\s*$" % re.escape(SECRET_KEY), text, re.M)
        value = m.group(1).strip("'\"") if m else None
    if not value:
        raise DSMError("secret '%s' not found in %s" % (SECRET_KEY, SECRETS_FILE))
    return str(value)


def _tls_context():
    # Chain/hostname checks are replaced by the fingerprint pin in _connect().
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def fingerprint(nas):
    conn = http.client.HTTPSConnection(nas["host"], nas["port"], timeout=TIMEOUT, context=_tls_context())
    conn.connect()
    try:
        return hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
    finally:
        conn.close()


class DSM:
    def __init__(self, name):
        self.name = name
        self.nas = NAS[name]
        if not self.nas.get("sha256"):
            raise DSMError("no pinned certificate for %s; run '%s fingerprint' and add it to NAS"
                           % (name, name))
        self.sid = None
        self.token = None

    def _connect(self):
        conn = http.client.HTTPSConnection(self.nas["host"], self.nas["port"], timeout=TIMEOUT,
                                           context=_tls_context())
        conn.connect()
        seen = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        if seen != self.nas["sha256"]:
            conn.close()
            raise DSMError("%s certificate changed (now sha256 %s); nothing was sent. If DSM renewed "
                           "its certificate, confirm it there and update the pin" % (self.name, seen))
        return conn

    def _post(self, params):
        conn = self._connect()  # pin checked before the request (and password) is sent
        try:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if self.token:
                headers["X-SYNO-TOKEN"] = self.token
            conn.request("POST", "/webapi/entry.cgi", urllib.parse.urlencode(params), headers)
            resp = conn.getresponse()
            if resp.status != 200:
                raise DSMError("HTTP %s from %s" % (resp.status, self.name))
            return json.loads(resp.read())
        finally:
            conn.close()

    def login(self):
        r = self._post({
            "api": "SYNO.API.Auth", "version": "6", "method": "login",
            "account": ACCOUNT, "passwd": REDACTED, "session": SESSION,
            "format": "sid", "enable_syno_token": "yes",
        })
        if not r.get("success"):
            code = (r.get("error") or {}).get("code")
            hint = {400: "wrong password", 401: "account disabled", 402: "permission denied",
                    403: "2-step verification required", 407: "IP blocked"}.get(code, "")
            raise DSMError("login as %s failed: code %s %s" % (ACCOUNT, code, hint))
        self.sid = r["data"]["sid"]
        self.token = REDACTED

    def call(self, api, method, version=1, **params):
        p = {"api": api, "method": method, "version": str(version), "_sid": self.sid}
        p.update({k: str(v) for k, v in params.items()})
        r = self._post(p)
        if not r.get("success"):
            code = (r.get("error") or {}).get("code")
            hint = {105: " (permission denied: local-api needs to be an administrator)",
                    160: " (local-api is not allowed to use this app: check Application Privileges)"}.get(code, "")
            raise DSMError("%s %s failed: code %s%s" % (api, method, code, hint))
        return r.get("data") or {}

    def logout(self):
        if not self.sid:
            return
        try:
            self._post({"api": "SYNO.API.Auth", "version": "6", "method": "logout",
                        "session": SESSION, "_sid": self.sid})
        except Exception:
            pass


def scrub_pools(dsm):
    """Storage pools that support scrubbing, with the API and space_id Storage Manager uses."""
    info = dsm.call("SYNO.Storage.CGI.Storage", "load_info")
    pools = []
    for p in info.get("storagePools") or []:
        deploy = p.get("deploy_path") or ""
        single = p.get("raidType") == "single"
        if single and "iscsilun" in deploy:
            continue
        api = "SYNO.Storage.CGI.Volume" if single and "volume" in deploy else "SYNO.Storage.CGI.Pool"
        try:
            pct = float((p.get("progress") or {}).get("percent"))
        except (TypeError, ValueError):
            pct = None
        if pct is not None and pct < 0:
            pct = None
        pools.append({
            "id": p.get("id"),
            "api": api,
            "state": p.get("scrubbingStatus") or "",
            "pool_status": p.get("status") or "",
            "percent": pct,
            "scheduled": bool(p.get("is_scheduled")),
        })
    return pools


def is_running(pool):
    return pool["state"] in ("kernel_running", "running") or pool["pool_status"] == "background_scrubbing"


def is_paused(pool):
    return pool["state"] == "paused"


def index_status(dsm):
    s = dsm.call("SYNO.Finder.FileIndexing.Status", "get").get("status") or {}
    raw = str(s.get("index", ""))
    if raw.isdigit():  # while paused, DSM reports the seconds left until it resumes itself
        return {"index_state": "paused", "index_resume_in": int(raw), "index_raw": raw}
    state = {"processing": "running", "finished": "idle"}.get(raw, raw or "unknown")
    return {"index_state": state, "index_resume_in": None, "index_raw": raw}


def status(dsm):
    pools = scrub_pools(dsm)
    if any(is_running(p) for p in pools):
        scrub = "running"
    elif any(is_paused(p) for p in pools):
        scrub = "paused"
    else:
        scrub = "idle"
    pct = next((p["percent"] for p in pools if is_running(p) and p["percent"] is not None), None)
    out = {"scrub_state": scrub, "scrub_percent": pct, "scrub_pools": pools}
    try:
        out.update(index_status(dsm))
    except DSMError as e:  # e.g. code 160: local-api lacks the Universal Search app privilege
        out.update({"index_state": "error", "index_resume_in": None, "index_raw": str(e)})
    out["checked"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out


def pause_scrub(dsm):
    done = []
    schedule_paused = False
    for p in scrub_pools(dsm):
        if not is_running(p):
            continue
        if p["scheduled"]:
            if not schedule_paused:  # the schedule pause applies to all scheduled pools at once
                dsm.call("SYNO.Storage.CGI.Storage", "set_data_scrubbing_schedule_status", schedule_status="1")
                schedule_paused = True
            done.append(p["id"] + " (schedule)")
        else:
            dsm.call(p["api"], "pause_data_scrubbing", space_id=p["id"])
            done.append(p["id"])
    return done


def resume_scrub(dsm):
    done = []
    schedule_resumed = False
    for p in scrub_pools(dsm):
        if not is_paused(p):  # never start a scrub that wasn't already paused
            continue
        if p["scheduled"]:
            if not schedule_resumed:
                dsm.call("SYNO.Storage.CGI.Storage", "set_data_scrubbing_schedule_status", schedule_status="0")
                schedule_resumed = True
            done.append(p["id"] + " (schedule)")
        else:
            dsm.call(p["api"], "data_scrubbing", space_id=p["id"], force="false")
            done.append(p["id"])
    return done


def backup_tasks(dsm):
    # Hyper Backup tasks with the state and status DSM reports for each
    data = dsm.call("SYNO.Backup.Task", "list")
    out = []
    for t in data.get("task_list") or []:
        out.append({
            "id": t.get("task_id"),
            "name": t.get("name") or t.get("task_name"),
            "state": t.get("state"),
            "status": t.get("status"),
        })
    return out


def backup_task(dsm, argv):
    # Find the Hyper Backup task named by argv[3] (a numeric task id)
    if len(argv) < 4 or not argv[3].isdigit():
        raise DSMError("%s needs a numeric Hyper Backup task id" % argv[2])
    want = int(argv[3])
    for t in dsm.call("SYNO.Backup.Task", "list").get("task_list") or []:
        if int(t.get("task_id", -1)) == want:
            return t
    raise DSMError("no Hyper Backup task with id %d" % want)


def throttle_state(nas):
    # Ask Calliope which interfaces carry the throttle. Read-only; never changes anything.
    cfg = THROTTLE_SSH.get(nas)
    if not cfg:
        raise DSMError("no throttle control set up for %s" % nas)
    cmd = ["ssh", "-i", cfg["key"], "-p", cfg["port"], "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
           "-o", "ConnectTimeout=8", "-o", "UserKnownHostsFile=%s" % cfg["known_hosts"],
           "-o", "StrictHostKeyChecking=yes", "%s@%s" % (cfg["user"], cfg["host"])]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if p.returncode != 0:
        raise DSMError("reading throttle state failed: %s" % (p.stderr.strip() or "ssh exit %d" % p.returncode))
    devices = {}
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("on", "off"):
            devices[parts[0]] = (parts[2] if len(parts) > 2 else "on") if parts[1] == "on" else "off"
    if not devices:
        raise DSMError("unexpected throttle status output: %r" % p.stdout[:200])
    active = {d: r for d, r in devices.items() if r != "off"}
    return {
        "throttle": "on" if active else "off",
        "throttle_rate": next(iter(active.values())) if active else None,
        "throttle_devices": devices,
        "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def throttle(nas, action):
    if action == "throttle_status":
        return throttle_state(nas)
    want = "on" if action == "throttle_on" else "off"
    dsm = DSM(nas)
    dsm.login()
    try:
        # DSM's Task Scheduler "run" exists only in versions 1 and 2 (3 and 4 answer error 103);
        # version 2 takes a "tasks" array of {id, real_owner} and runs disabled tasks too.
        tasks = json.dumps([{"id": THROTTLE_TASKS[action], "real_owner": "root"}])
        dsm.call("SYNO.Core.TaskScheduler", "run", version=2, tasks=tasks)
    finally:
        dsm.logout()
    state = None
    for _ in range(10):  # the root task starts asynchronously, give it a few seconds
        time.sleep(1.5)
        state = throttle_state(nas)
        if state["throttle"] == want:
            break
    state["acted_on"] = ["throttle %s (DSM task %d)" % (want, THROTTLE_TASKS[action])]
    if state["throttle"] != want:
        raise DSMError("ran DSM task %d but the throttle still reads '%s'" % (THROTTLE_TASKS[action], state["throttle"]))
    return state


def main(argv):
    if len(argv) < 3 or argv[1] not in NAS or argv[2] not in ACTIONS:
        raise DSMError("usage: %s <%s> <%s> [hours]" % (argv[0], "|".join(NAS), "|".join(ACTIONS)))
    nas, action = argv[1], argv[2]
    hours = 6
    if action == "pause_index" and len(argv) > 3 and argv[3] != "":
        try:
            hours = int(float(argv[3]))
        except ValueError:
            raise DSMError("hours must be a number")
        if hours not in INDEX_PAUSE_HOURS:
            raise DSMError("hours must be one of %s (0 = until resumed)" % (INDEX_PAUSE_HOURS,))

    if action in THROTTLE_ACTIONS:
        result = throttle(nas, action)
        result["nas"] = nas
        print(json.dumps(result))
        return

    if action == "fingerprint":  # no login, nothing sent: just report the certificate
        print(json.dumps({"nas": nas, "sha256": fingerprint(NAS[nas])}))
        return

    dsm = DSM(nas)
    dsm.login()
    try:
        result = {}
        if action == "pause_scrub":
            result["acted_on"] = pause_scrub(dsm)
        elif action == "resume_scrub":
            result["acted_on"] = resume_scrub(dsm)
        elif action == "pause_index":
            dsm.call("SYNO.Finder.FileIndexing.Status", "pause", length=hours)
            result["acted_on"] = ["index (%s)" % ("until resumed" if hours == 0 else "%dh" % hours)]
        elif action == "resume_index":
            dsm.call("SYNO.Finder.FileIndexing.Status", "resume")
            result["acted_on"] = ["index"]
        elif action == "pause_backup":
            t = backup_task(dsm, argv)
            dsm.call("SYNO.Backup.Task", "suspend", task_id=t["task_id"], task_state=t.get("state") or "backupable")
            result["acted_on"] = ["backup task %s (%s)" % (t["task_id"], t.get("name") or t.get("task_name"))]
        elif action == "resume_backup":
            t = backup_task(dsm, argv)
            dsm.call("SYNO.Backup.Task", "resume", task_id=t["task_id"])
            result["acted_on"] = ["backup task %s (%s)" % (t["task_id"], t.get("name") or t.get("task_name"))]
        if action in BACKUP_ACTIONS:
            result["backup_tasks"] = backup_tasks(dsm)
            result["checked"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        else:
            result.update(status(dsm))
    finally:
        dsm.logout()
    result["nas"] = nas
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main(sys.argv)
    except DSMError as e:
        print("synology_maintenance: %s" % e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # network errors, bad JSON
        print("synology_maintenance: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        sys.exit(1)
