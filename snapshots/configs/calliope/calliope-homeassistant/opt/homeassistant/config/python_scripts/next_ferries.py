target_id = data.get('target_id')
primary_entity_id = data.get('entity_id')
secondary_entity_id = data.get('secondary_entity_id')

# Gather departures from active/inactive sources
next_departures_list = []
for entity_id in (primary_entity_id, secondary_entity_id):
    if entity_id:
        state = hass.states.get(entity_id)
        if state is not None and state.state not in ('unavailable', 'unknown'):
            next_departures_list.extend(state.attributes.get('next_departures', []))

# Timezone-aware local and UTC datetimes
now_local = dt_util.now()
now_utc = dt_util.utcnow()
current_time_unix = now_utc.timestamp()

# End of current local day in epoch seconds
midnight_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
midnight_unix = midnight_local.timestamp()

# Parse, localize, and deduplicate GTFS departure strings
departures_dt = []
seen_timestamps = set()

for dep_str in next_departures_list:
    dt = dt_util.parse_datetime(dep_str)
    if dt is not None:
        if dt.tzinfo is None:
            # GTFS string is naive local time -> attach Home Assistant local timezone
            dt = dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        
        ts = dt.timestamp()
        if ts >= current_time_unix and ts not in seen_timestamps:
            seen_timestamps.add(ts)
            departures_dt.append((ts, dt))

# Sort chronologically and keep the next 5
departures_dt.sort(key=lambda x: x[0])
next_five = departures_dt[:5]

departure_info = {}
for ts, dt in next_five:
    day = 'tomorrow' if ts > midnight_unix else 'today'
    departure_info[ts] = {
        'day': day,
        'first': False,
        'last': False,
        'iso': dt_util.as_utc(dt).isoformat()
    }

# Flag first departure tomorrow and last departure today
for ts, info in departure_info.items():
    if info['day'] == 'tomorrow':
        info['first'] = True
        keys = list(departure_info.keys())
        idx = keys.index(ts)
        if idx > 0:
            departure_info[keys[idx - 1]]['last'] = True
        break

# Assign labels
for ts, info in departure_info.items():
    if info['first'] and info['day'] == 'tomorrow':
        info['label'] = 'FIRST tomorrow'
    elif info['first']:
        info['label'] = 'FIRST'
    elif info['last']:
        info['label'] = 'LAST FERRY'
    else:
        info['label'] = ''

# Write output sensors
for i, (ts, info) in enumerate(departure_info.items(), start=1):
    sensor_name = f"{target_id}_next_{i}"
    hass.states.set(sensor_name, info['iso'], {
        'device_class': 'timestamp',
        'last': info.get('last', False),
        'first': info.get('first', False),
        'day': info['day'],
        'label': info['label']
    })

output['departure_info'] = departure_info