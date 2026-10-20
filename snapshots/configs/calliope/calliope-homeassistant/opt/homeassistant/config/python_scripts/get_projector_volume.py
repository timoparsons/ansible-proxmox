#!/usr/bin/env python3
import requests
import json

url = "http://10.1.1.80:6095/general?action=getVolum"

try:
    response = requests.get(url, timeout=5)
    data = response.json()['data']
    nested_data = json.loads(data)
    volume = nested_data['volum']
    print(volume)
except (requests.RequestException, json.JSONDecodeError):
    print("0")

exit()
