"""
main.py
MATRIX Testbed — Raspberry Pi Middleware Entry Point

Launches all four concurrent async tasks:
  1. siemens_client  — OPC-UA client → S7-1200 (Turntable)
  2. ab_client       — Modbus TCP client → Micro820 (Transfer Unit)
  3. opta_client     — Modbus TCP client → Opta (Conveyor)
  4. opcua_server    — OPC-UA server → Ignition SCADA

Run on the Raspberry Pi:
    python main.py

"""

import asyncio
import logging
import signal

import siemens_client
import ab_client
import opta_client
import opcua_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("MIDDLEWARE")


async def run():
    log.info("MATRIX middleware starting...")
    log.info("  Task 1 : Siemens S7-1200  OPC-UA client")
    log.info("  Task 2 : Allen-Bradley    Modbus TCP client")
    log.info("  Task 3 : Arduino Opta     Modbus TCP client")
    log.info("  Task 4 : OPC-UA server    → Ignition SCADA")

    tasks = await asyncio.gather(
        siemens_client.run(),
        ab_client.run(),
        opta_client.run(),
        opcua_server.run(),
        return_exceptions=True
    )

    for i, result in enumerate(tasks):
        if isinstance(result, Exception):
            log.error(f"Task {i+1} exited with error: {result}")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Middleware stopped by user.")
