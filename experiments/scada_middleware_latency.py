"""
    Script that measures tag read/write latency between RaspberryPi and Scada Layer,
    one sample per protocol per device, over N repeated single-value reads.
    
    Author: Kananelo V
"""

import time
import statistics
from asyncua.sync import Client as OpcClient


SAMPLES = 500

f = open(r"..\data\scada_middleware_latency.csv", "w")
f.write("device,protocol,sample_index,latency_ms\n")


def _write_samples(f, label, protocol, times):
    """One CSV row per sample — keeps the output directly loadable by pandas."""
    device = label.split("(")[0].strip()
    for i, t in enumerate(times):
        f.write(f"{device},{protocol},{i},{t}\n")


def measure_opcua(ip, label, node_id):
    times = []
    print(f"connecting to {ip}...", flush=True)
    with OpcClient(f"opc.tcp://{ip}:4840") as client:
        node = client.get_node(node_id)
        for _ in range(SAMPLES):
            t0 = time.perf_counter()
            node.read_value()
            times.append((time.perf_counter() - t0) * 1000)
    print(f"{label}: mean={statistics.mean(times):.2f}ms  "
          f"std={statistics.stdev(times):.2f}ms  "
          f"min={min(times):.2f}ms  max={max(times):.2f}ms", flush=True)
    _write_samples(f, label, "OPC UA", times)
    return times



measure_opcua("192.168.100.10", "RPi-Middleware", "ns=4;i=4")

# Save results to CSV
f.close()