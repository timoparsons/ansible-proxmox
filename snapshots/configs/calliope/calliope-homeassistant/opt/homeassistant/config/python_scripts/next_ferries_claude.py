
def script_main():
    # Get the entity_id of the sensor from the data passed to the script
    sensor_entity_id = data.get('entity_id')
    if not sensor_entity_id:
        logger.error("No entity_id provided")
        return

    # Get the state of the sensor
    sensor_state = hass.states.get(sensor_entity_id)
    if not sensor_state:
        logger.error(f"Could not find state for entity {sensor_entity_id}")
        return

    next_departures_list = sensor_state.attributes.get('next_departures', [])
    
    # Current time using dt_util
    current_time = dt_util.utcnow()
    current_time_unix = current_time.timestamp()
    
    # Get current times
    current_time_utc = hass.states.get("sensor.date_time_utc").state
    current_time_local = hass.states.get("sensor.date_time").state
    
    # Parse times 
    utc_time = dt_util.parse_datetime(current_time_utc)
    local_time = dt_util.parse_datetime(current_time_local)
    
    # Calculate the UTC offset
    utc_offset_seconds = (local_time - utc_time).total_seconds()
    utc_offset_hours = utc_offset_seconds / 3600
    
    # Set the midnight time
    midnight_local = local_time.replace(hour=23, minute=59, second=59, microsecond=999999)
    midnight_local_unix = midnight_local.timestamp()
    
    # Add the UTC offset to midnight
    midnight_offset = midnight_local_unix + 3600*2
    
    # Initialize variables for next departures
    next_five_departures = []
    departure_info = {}
    
    # Collect next departures
    for departure_str in next_departures_list:
        departure_datetime = dt_util.parse_datetime(departure_str)
        departure_time = departure_datetime.timestamp()
        
        if departure_time >= current_time_unix:
            next_five_departures.append(departure_time)
            if len(next_five_departures) == 5:
                break
    
    # Sort departures
    next_five_departures.sort()
    
    # Process departures
    for departure in next_five_departures:
        # Determine day
        day = 'tomorrow' if departure > midnight_offset else 'today'
        
        # Store departure information
        departure_info[departure] = {
            'day': day, 
            'first': False, 
            'last': False,
            'timestamp': dt_util.utc_from_timestamp(departure).isoformat()
        }
    
    # Identify first and last departures
    sorted_departures = sorted(departure_info.keys())
    for i, departure in enumerate(sorted_departures):
        info = departure_info[departure]
        
        # First tomorrow logic
        if info['day'] == 'tomorrow':
            info['first'] = True
            
            # Mark previous departure as last for today
            if i > 0:
                previous_departure = sorted_departures[i-1]
                departure_info[previous_departure]['last'] = True
            break
    
    # Add labels and display information
    for departure, info in departure_info.items():
        # Set label based on departure characteristics
        if info['first'] and info['day'] == 'tomorrow':
            info['label'] = 'FIRST tomorrow'
        elif info['first']:
            info['label'] = 'FIRST'
        elif info.get('last'):
            info['label'] = 'LAST FERRY'
        elif info['day'] == 'tomorrow':
            info['label'] = 'tomorrow'
        else:
            info['label'] = ''
    
    # Set sensors for each departure
    for i, (departure, info) in enumerate(departure_info.items(), start=1):
        sensor_name = f"{sensor_entity_id}_next_{i}"
        
        hass.states.set(sensor_name, info['timestamp'], {
            'last': info.get('last', False),
            'first': info.get('first', False),
            'day': info['day'],
            'label': info['label']
        })
    
    # Include departure info in output
    output['departure_info'] = departure_info

# Execute the script
script_main()