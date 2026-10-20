# frigate_save_notification_snapshot.py

import requests
import os

def save_image(event_id):
    api_url = f"http://127.0.0.1:8443/api/frigate/notifications/{event_id}/snapshot.jpg"
    output_folder = "/config/www/"
    output_file = os.path.join(output_folder, f"{event_id}.jpg")

    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            with open(output_file, 'wb') as f:
                f.write(response.content)
            return True
        else:
            return False
    except Exception as e:
        return False

# Call the function with the event_id
event_id = "{{ id }}"
saved = save_image(event_id)
if saved:
    print("Image saved successfully.")
else:
    print("Failed to save image.")
