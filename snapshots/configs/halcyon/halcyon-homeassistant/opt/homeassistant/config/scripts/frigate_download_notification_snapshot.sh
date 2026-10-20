#!/bin/bash

# Usage: frigate_download_notification_snapshot.sh event_id output_folder

event_id=$1
output_folder=$2
output_file="${output_folder}/driveway_snapshot.jpg"
api_url="http://127.0.0.1:8443/api/frigate/notifications/${event_id}/snapshot.jpg"

wget -O "$output_file" "$api_url"
