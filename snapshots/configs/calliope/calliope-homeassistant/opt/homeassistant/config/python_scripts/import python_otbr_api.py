#!/Users/tim/homeassistant/bin/python3.11

import sys
sys.path.insert(0, '/Users/tim/homeassistant/lib/python3.11/site-packages')
import python_otbr_api
from python_otbr_api import PENDING_DATASET_DELAY_TIMER, tlv_parser
from python_otbr_api.pskc import compute_pskc
from python_otbr_api.tlv_parser import MeshcopTLVType, MeshcopTLVItem

# Apple
CHANNEL = 25
PANID = "396c"
EXTPANID = "62a812e7c0d34440"
NETWORK_KEY = REDACTED
NETWORK_NAME = "MyHome1889279811"
PSKC = REDACTED
TIMESTAMP = b'\x00\x00\x00\x00\x00\x03\x00\x00'

channel = MeshcopTLVItem(tag=0, data=CHANNEL.to_bytes(length=3, byteorder='big'))
pan_id= MeshcopTLVItem(tag=1, data=bytes.fromhex(PANID))
ext_pan_id = MeshcopTLVItem(tag=2, data=bytes.fromhex(EXTPANID))
network_name = MeshcopTLVItem(tag=3, data=str.encode(NETWORK_NAME))
pre_shared_key = REDACTED
network_key = REDACTED
timestamp = MeshcopTLVItem(tag=14, data=TIMESTAMP)

tlv_new = {0: channel, 1: pan_id, 2: ext_pan_id, 3: network_name, 4: pre_shared_key, 5: network_key, 14: timestamp}
tlv  = tlv_parser.encode_tlv(tlv_new)
print(tlv)