#!/bin/bash

# Usage: frigate_capture_stream_snapshot.sh camera_name output_folder

camera_name=$1
output_folder=$2

# Download the video snapshot
video_url="http://10.2.1.28:1984/api/frame.mp4?src=${camera_name}"
video_path="${output_folder}/${camera_name}.mp4"
wget -O "$video_path" "$video_url"



# Step 2: Convert the video snapshot to a single frame (jpg)
image_path="${output_folder}/${camera_name}_grab.jpg"
ffmpeg -y -i "$video_path" -q:v 10 -vf scale=1280:720 -frames:v 1 -preset ultrafast -r 1 "$image_path"

# Step 3: Cleanup - delete the downloaded video snapshot
rm "$video_path"



