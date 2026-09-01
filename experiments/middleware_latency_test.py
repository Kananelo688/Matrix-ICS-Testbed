"""
    Script that measures latency between the middleware RPi and each PLC,
    one sample per protocol per device, over N repeated single-value reads.
    
    Author: Kananelo V
"""

import time
import statistics
from pymodbus.client import ModbusTcpClient
from asyncua.sync import Client as OpcClient
from pycomm3 import LogixDriver

SAMPLES = 500

f = open("scada_middleware_latency.csv", "w")
f.write("device,protocol,sample_index,latency_ms\n")


def _write_samples(f, label, protocol, times):
    """One CSV row per sample — keeps the output directly loadable by pandas."""
    device = label.split("(")[0].strip()
    for i, t in enumerate(times):
        f.write(f"{device},{protocol},{i},{t}\n")


def measure_modbus(ip, label, slave_id):
    print(f"connecting to {ip}...", flush=True)
    client = ModbusTcpClient(ip, port=502)
    client.connect()
    times = []
    print(f"sending read coil requests...", flush=True)
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        client.read_coils(address=0, count=1, slave=slave_id)
        times.append((time.perf_counter() - t0) * 1000)  # ms
    client.close()
    print(f"{label}: mean={statistics.mean(times):.2f}ms  "
          f"std={statistics.stdev(times):.2f}ms  "
          f"min={min(times):.2f}ms  max={max(times):.2f}ms", flush=True)
    _write_samples(f, label, "Modbus TCP", times)
    return times

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

def measure_cip(ip, label, tag_name):
    """
        Measures EtherNet/IP (CIP) round-trip latency for a single symbolic
        tag read against the Micro820, using pycomm3 (synchronous — no
        asyncio wrapping needed for this standalone benchmark script).
    """
    print(f"connecting to {ip}...", flush=True)
    times = []
    with LogixDriver(ip) as plc:
        print(f"sending CIP tag read requests...", flush=True)
        for _ in range(SAMPLES):
            t0 = time.perf_counter()
            result = plc.read(tag_name)
            if result.error: #type:ignore
                print(f"  read error: {result.error}", flush=True) #type:ignore
                continue
            times.append((time.perf_counter() - t0) * 1000)
    print(f"{label}: mean={statistics.mean(times):.2f}ms  "
          f"std={statistics.stdev(times):.2f}ms  "
          f"min={min(times):.2f}ms  max={max(times):.2f}ms", flush=True)
    _write_samples(f, label, "EtherNet/IP", times)
    return times


#measure_cip("192.168.50.20", "Allen-Bradley Micro820 (EtherNet/IP)", "SchneiderModbusHandshake")
#measure_modbus("192.168.50.50", "Schneider TM221 (Modbus TCP)", 1)
measure_opcua("192.168.100.10", "RPi Middleware<->SCADA (OPC UA)", "ns=2;i=32")
#measure_opcua("192.168.100.10", "Middleware OPC-UA (aggregated)","ns=MATRIX.Middleware.OPC-UA, i=4")

# Save results to CSV
f.close()