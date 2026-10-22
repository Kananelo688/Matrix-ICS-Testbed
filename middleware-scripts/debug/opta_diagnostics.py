# diagnostic_scan.py — run this standalone to find your register addresses
import asyncio
from pymodbus.client import AsyncModbusTcpClient

PLC_IP  = "192.168.50.30"
UNIT_ID = 255

async def scan():
    client = AsyncModbusTcpClient(PLC_IP, port=502, timeout=10)
    await client.connect()
    await asyncio.sleep(1)
    print(f"Connected: {client.connected}\n")

    # Scan Holding Registers (FC03) — addresses 0 to 19
    print("── FC03 Holding Registers ──────────────")
    for addr in range(20):
        r = await client.read_holding_registers(addr, count=1, slave=UNIT_ID)
        if not r.isError():
            print(f"  HR[{addr}] = {r.registers[0]}")
        else:
            print(f"  HR[{addr}] = ERROR: {r}")

    # Scan Input Registers (FC04) — addresses 0 to 19
    print("\n── FC04 Input Registers ────────────────")
    for addr in range(20):
        r = await client.read_input_registers(addr, count=1, slave=UNIT_ID)
        if not r.isError():
            print(f"  IR[{addr}] = {r.registers[0]}")
        else:
            print(f"  IR[{addr}] = ERROR: {r}")

    client.close()

asyncio.run(scan())