#!/usr/bin/env python3
# Ferry timetable from the gtfs2 GTFS database (read-only), for a command_line sensor.
# Usage: ferry_timetable.py to_city|to_devonport
# Outputs: count and departures (all of today), html (grid for the pop-up), next (next 4 departures
# from now, today then tomorrow, with first/last flags). Merges every pier that serves the route,
# so a switch between Downtown Pier 2 and Pier 4 needs no change here.
import sqlite3, json, sys, datetime

DB = 'file:/config/gtfs2/akltransport.sqlite?mode=ro'
ROUTE = 'DEV-209'
DIRS = {
    'to_city': (0, ['9670-6a81c363']),                       # Devonport terminal
    'to_devonport': (1, ['9702-e5f42777', '9704-5aba6459']),  # Downtown Pier 2 and Pier 4
}
direction, origins = DIRS[sys.argv[1]]
now = datetime.datetime.now().astimezone()
today = now.date()
tomorrow = today + datetime.timedelta(days=1)
DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
c = sqlite3.connect(DB, uri=True)


def minutes_for(day):
    iso = day.isoformat()
    active = set(r[0] for r in c.execute(
        'select service_id from calendar where %s=1 and start_date<=? and end_date>=?' % DAYS[day.weekday()], (iso, iso)))
    for sid, etype in c.execute('select service_id, exception_type from calendar_dates where date=?', (iso,)):
        if etype == 1:
            active.add(sid)
        elif etype == 2:
            active.discard(sid)
    found = set()
    if active:
        q = ('select st.departure_time from stop_times st join trips t on t.trip_id=st.trip_id '
             'where t.route_id=? and t.direction_id=? and st.stop_id in (%s) and t.service_id in (%s)' % (
                 ','.join('?' * len(origins)), ','.join('?' * len(active))))
        for (dep,) in c.execute(q, [ROUTE, direction] + origins + sorted(active)):
            t = datetime.datetime.strptime(dep[:19], '%Y-%m-%d %H:%M:%S')
            # Times past midnight are stored on 1970-01-02.
            found.add((t.day - 1) * 1440 + t.hour * 60 + t.minute)
    return sorted(found)


def at(day, m):
    return (datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=m)).astimezone()


fmt = lambda m: '%02d:%02d' % ((m // 60) % 24, m % 60)
out = minutes_for(today)
out_tomorrow = minutes_for(tomorrow)

# Upcoming departures from now, today then tomorrow.
upcoming = [(today, 'today', m) for m in out if at(today, m) >= now]
upcoming += [(tomorrow, 'tomorrow', m) for m in out_tomorrow]
nxt = []
for day, name, m in upcoming[:4]:
    is_last = bool(out) and name == 'today' and m == out[-1]
    is_first = name == 'tomorrow' and m == out_tomorrow[0]
    label = 'LAST FERRY' if is_last else ('FIRST tomorrow' if is_first else '')
    nxt.append({'iso': at(day, m).astimezone(datetime.timezone.utc).isoformat(), 'day': name,
                'label': label, 'last': is_last, 'first': is_first})

# Grid for the pop-up: past dimmed, next bold in the primary colour, last ferry red.
now_m = now.hour * 60 + now.minute
nxt_today = next((m for m in out if m >= now_m), None)
spans = []
for i, m in enumerate(out):
    style = ''
    if m < now_m:
        style = 'opacity:.35'
    elif m == nxt_today:
        style = 'font-weight:bold;color:var(--primary-color)'
    if i == len(out) - 1:
        style = 'font-weight:bold;color:var(--error-color)' + (';opacity:.35' if m < now_m else '')
    spans.append('<span style="%s">%s</span>' % (style, fmt(m)))
html = '<div style="display:flex;flex-wrap:wrap;gap:4px 14px;font-size:14px;margin:-8px -4px">%s</div>' % ''.join(spans)

print(json.dumps({'count': len(out), 'date': today.isoformat(), 'departures': [fmt(m) for m in out],
                  'html': html, 'next': nxt}))
