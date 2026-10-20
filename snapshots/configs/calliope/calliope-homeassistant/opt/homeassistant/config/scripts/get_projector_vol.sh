#!/bin/bash

# Make an HTTP request to get the projector volume
volume=$(curl -s http://10.1.1.16:6095/general?action=getVolum | jq -r '.volum')

# Log the volume
echo "Projector Volume: $volume"
