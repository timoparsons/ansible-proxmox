#!/usr/bin/env python3
"""
Sonos Multi-Device Audio Clip Script (HAOS Compatible - Curl Version)
Plays audio clips or chimes on multiple Sonos devices simultaneously

Usage: python3 sonos_chime.py [volume] [audio_file_or_name] [description]
Examples:
  python3 sonos_chime.py                           # Default chime at volume 100
  python3 sonos_chime.py 20                        # Chime at volume 75
  python3 sonos_chime.py 80 doorbell.mp3          # Play doorbell.mp3 at volume 80
  python3 sonos_chime.py 20 /config/www/sounds/dingdong.wav "Doorbell" # Play specific file
"""

import threading
import sys
import json
import logging
import os
import time
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration - Update these with your Sonos devices
SONOS_DEVICES = [
    {
        "name": "Lounge",
        "ip": "10.1.1.90",
        "port": 1443,
        "player_id": "RINCON_5CAAFD0CF48A01400",
        "default_volume": 50  # Optional: device-specific default volume
    },
    {
        "name": "TV Room",
        "ip": "10.1.1.91",
        "port": 1443,
        "player_id": "RINCON_347E5C71CB8D01400",
        "default_volume": 50  # Optional: device-specific default volume
    },
    {
        "name": "Office",
        "ip": "10.1.1.94",
        "port": 1443,
        "player_id": "RINCON_48A6B8A8C04201400",
        "default_volume": 10  # Optional: device-specific default volume
    }

]


# Sonos API Configuration
# The Sonos API key is read from secrets.yaml (key REDACTED) instead of being stored in this file.
SECRETS_FILE = REDACTED
SECRET_KEY = REDACTED


def read_secret(key=SECRET_KEY):
    with open(SECRETS_FILE, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml
        value = yaml.safe_load(text).get(key)
    except ImportError:
        value = None
        for line in text.splitlines():
            if line.startswith(key + ":"):
                value = line.split(":", 1)[1].strip().strip(chr(34) + chr(39))
    if not value:
        sys.exit("secret not found in " + SECRETS_FILE)
    return str(value)


SONOS_API_KEY = REDACTED
APP_ID = "com.acme.app"

# Home Assistant Configuration
HA_BASE_URL = "http://homeassistant.local:8443"  # Update with your HA URL
HA_MEDIA_PATH = "/config/www/sounds/"  # Default path for audio files
HA_TOKEN = REDACTED


def resolve_audio_source(audio_input):
    """
    Resolve audio input to either a URL or indicate it's the built-in chime.
    Returns: (is_chime: bool, url_or_none: str|None, display_name: str)
    """
    if not audio_input or audio_input.upper() == "CHIME":
        return True, None, "Built-in Chime"
    
    # If it's already a full URL, use it directly
    if audio_input.startswith(('http://', 'https://')):
        return False, audio_input, audio_input
    
    # Check if it's an absolute file path
    if audio_input.startswith('/'):
        if os.path.exists(audio_input):
            # Convert to HA URL (assuming the file is accessible via HA's web server)
            relative_path = audio_input.replace('/config/www/', '')
            url = f"{HA_BASE_URL}/local/{relative_path}"
            return False, url, audio_input
        else:
            logger.warning(f"File not found: {audio_input}")
            return True, None, "Built-in Chime (file not found)"
    
    # Try as relative path in the default sounds directory
    full_path = os.path.join(HA_MEDIA_PATH, audio_input)
    if os.path.exists(full_path):
        # Convert to HA URL
        relative_path = audio_input
        url = f"{HA_BASE_URL}/local/sounds/{relative_path}"
        return False, url, audio_input
    else:
        # Try in /config/www/ directory
        www_path = f"/config/www/{audio_input}"
        if os.path.exists(www_path):
            url = f"{HA_BASE_URL}/local/{audio_input}"
            return False, url, audio_input
        else:
            logger.warning(f"Audio file not found: {audio_input}. Using built-in chime instead.")
            return True, None, "Built-in Chime (file not found)"


def play_audio_clip_curl(device, volume=20, audio_source=None, description="Audio Clip"):
    """Play audio clip on a single Sonos device using curl."""
    url = f"https://{device['ip']}:{device['port']}/api/v1/players/{device['player_id']}/audioClip"
    
    is_chime, stream_url, display_name = resolve_audio_source(audio_source)
    
    # Use device-specific volume if available, otherwise use provided volume
    device_volume = device.get('default_volume', volume)
    
    payload = {
        "name": description,
        "appId": APP_ID,
        "volume": int(device_volume),
        "priority": "HIGH"
    }
    
    # Only add streamUrl if it's not the built-in chime
    if not is_chime and stream_url:
        payload["streamUrl"] = stream_url
    
    try:
        logger.info(f"Playing '{display_name}' on {device['name']} at volume {device_volume}")
        
        # Build curl command
        curl_cmd = [
            "curl",
            "-X", "POST",
            "-k",  # Ignore SSL certificate errors
            "--connect-timeout", "10",
            "--max-time", "30",
            "-H", f"X-Sonos-Api-Key: {SONOS_API_KEY}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
            url
        ]
        
        # Execute curl command
        result = subprocess.run(
            curl_cmd,
            capture_output=True,
            text=True,
            timeout=35
        )
        
        if result.returncode == 0:
            try:
                response_data = json.loads(result.stdout)
                clip_type = response_data.get('clipType', 'CUSTOM')
                clip_id = response_data.get('id', 'Unknown ID')
                logger.info(f"✓ Success on {device['name']}: {clip_type} - {clip_id}")
                return True, device['name']
            except json.JSONDecodeError:
                # If response isn't JSON, check if curl succeeded
                if "HTTP" in result.stdout or len(result.stdout) > 0:
                    logger.info(f"✓ Success on {device['name']}: Command executed")
                    return True, device['name']
                else:
                    logger.error(f"✗ Failed on {device['name']}: Invalid response")
                    return False, device['name']
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            logger.error(f"✗ Failed on {device['name']}: {error_msg}")
            return False, device['name']
            
    except subprocess.TimeoutExpired:
        logger.error(f"✗ Timeout on {device['name']}: Request took too long")
        return False, device['name']
    except FileNotFoundError:
        logger.error(f"✗ Error on {device['name']}: curl command not found")
        return False, device['name']
    except Exception as e:
        logger.error(f"✗ Unexpected exception on {device['name']}: {str(e)}")
        return False, device['name']


def play_on_selected_devices(target_name=None, volume=20, audio_source=None, description="Audio Clip"):
    """
    Plays audio on a specific device if target_name is provided, 
    otherwise plays on all configured devices.
    """
    # Filter the device list
    if target_name:
        devices_to_use = [d for d in SONOS_DEVICES if d['name'].lower() == target_name.lower()]
        if not devices_to_use:
            logger.warning(f"Target device '{target_name}' not found in SONOS_DEVICES. Falling back to all.")
            devices_to_use = SONOS_DEVICES
    else:
        devices_to_use = SONOS_DEVICES

    results = []
    threads = []
    
    def worker(device):
        success, device_name = play_audio_clip_curl(device, volume, audio_source, description)
        results.append((success, device_name))
    
    for device in devices_to_use:
        thread = threading.Thread(target=worker, args=(device,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    return sum(1 for success, _ in results if success), len(devices_to_use)


def test_curl_availability():
    """Test if curl is available on the system."""
    try:
        result = subprocess.run(["curl", "--version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            logger.info("✓ curl is available")
            return True
        else:
            logger.error("✗ curl is not working properly")
            return False
    except FileNotFoundError:
        logger.error("✗ curl is not installed or not in PATH")
        return False
    except Exception as e:
        logger.error(f"✗ Error testing curl: {str(e)}")
        return False


def main():
    if not test_curl_availability():
        sys.exit(1)
    
    # Default values
    volume = 50
    audio_source = None 
    description = "Audio Clip"
    target_speaker = None
    
    # Get all device names for comparison
    valid_device_names = [d['name'].lower() for d in SONOS_DEVICES]
    
    args = sys.argv[1:]
    
    for arg in args:
        # 1. Check if it's a Volume (1-100)
        if arg.isdigit() and 1 <= int(arg) <= 100:
            volume = int(arg)
        
        # 2. Check if it matches a Speaker Name
        elif arg.lower() in valid_device_names:
            target_speaker = arg
            
        # 3. Check if it's an audio file/URL
        elif (arg.endswith(('.mp3', '.wav', '.m4a', '.flac')) or 
              arg.startswith(('http', '/')) or 
              arg.upper() == "CHIME"):
            audio_source = arg
            
        # 4. Use anything else as the Description
        else:
            description = arg

    # Execution
    start_time = time.time()
    try:
        successes, attempted = play_on_selected_devices(target_speaker, volume, audio_source, description)
        execution_time = time.time() - start_time
        
        logger.info(f"Finished: {successes}/{attempted} devices played in {execution_time:.2f}s")
        sys.exit(0 if successes > 0 else 1)
            
    except Exception as e:
        logger.error(f"Script failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()