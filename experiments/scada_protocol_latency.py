import time
import statistics
from pymodbus.client import ModbusTcpClient
from asyncua.sync import Client as OpcClient
import pandas as pd
SAMPLES = 500
bypass_data = pd.DataFrame(columns=["device", "protocol", "latency_ms"])
def measure_modbus(ip, label, slave_id):
    print(f"connecting to {ip}...", flush = True)
    client = ModbusTcpClient(ip, port=502)
    client.connect()
    times = []
    print(f"sending read coil requests...", flush = True)
    for _ in range(SAMPLES):
        t0 = time.perf_counter()
        client.read_coils(address = 0, count = 1, slave=slave_id)
        times.append((time.perf_counter() - t0) * 1000)  # ms
    client.close()
    print(f"{label}: mean={statistics.mean(times):.2f}ms  "
          f"std={statistics.stdev(times):.2f}ms  "
          f"min={min(times):.2f}ms  max={max(times):.2f}ms", flush = True)
    bypass_data.loc[len(bypass_data)] = [label.split("(")[0].strip(), "Modbus TCP", statistics.mean(times)]
    return times

def measure_opcua(ip, label, node_id):
    times = []
    print(f"connecting to {ip}...", flush = True)
    with OpcClient(f"opc.tcp://{ip}:4840") as client:
        node = client.get_node(node_id)
        for _ in range(SAMPLES):
            t0 = time.perf_counter()
            node.read_value()
            times.append((time.perf_counter() - t0) * 1000)
    print(f"{label}: mean={statistics.mean(times):.2f}ms  "
          f"std={statistics.stdev(times):.2f}ms  "
          f"min={min(times):.2f}ms  max={max(times):.2f}ms", flush=True)
    bypass_data.loc[len(bypass_data)] = [label.split("(")[0].strip(), "OPC UA", statistics.mean(times)]
    return times

measure_modbus("192.168.50.20", "Allen-Bradley Micro820 (Modbus TCP)", 1)
measure_modbus("192.168.50.30", "Schneider M221 (Modbus TCP)", 255)
measure_opcua("192.168.50.10",  "Siemens S7-1200 (OPC UA)", "ns=4;i=4")
#measure_opcua("192.168.100.10", "Middleware OPC-UA (aggregated)","ns=MATRIX.Middleware.OPC-UA, i=4")

# Save results to CSV
bypass_data.to_csv("latency_bypass_middleware.csv", index=False)