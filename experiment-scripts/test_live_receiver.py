"""Run on the SAME workstation as system_timing_live_test.py."""
import json
import socket

HOST = "127.0.0.1"
PORT = 55001

with socket.create_connection((HOST, PORT), timeout=5) as sock:
    sock.settimeout(None)
    print("Connected. Initial snapshots and subsequent changes will appear below.")
    with sock.makefile("r", encoding="utf-8") as lines:
        for line in lines:
            message = json.loads(line)
            print(f"{message['timestamp']}  {message['kind']:8}  "
                  f"{message['zone']}/{message['tag']} = {message['value']}")
