#!/usr/bin/env python3
"""
main.py
MATRIX Testbed — Raspberry Pi Middleware Entry Point

Launches all four concurrent async tasks:
  1. siemens_client  — OPC-UA client     → S7-1200 (Turntable)
  2. ab_cip_client   — EtherNet/IP (CIP)  → Micro820 (Transfer Unit)
  3. tm221_client    — Modbus TCP client  → TM221 (Conveyor)
  4. opcua_server    — OPC-UA server      → Ignition SCADA

Run on the Raspberry Pi (this is exactly what the systemd service executes):
    python main.py

# --------------------------------------------------------------------------
# CHANGE [MAIN-1] (2026-10-22): docstring corrected only.
# WHY: the previous docstring described the retired stack ("ab_client — Modbus
#      TCP", "opta_client — Modbus TCP → Opta"). The actual imports below have
#      long been ab_cip_client (EtherNet/IP) and tm221_client (Modbus TCP).
#      The text was misleading for anyone reading the file cold.
# IMPACT: NONE. This is a comment-only change. The imports, task list, launch
#      order and runtime behaviour are byte-for-byte identical to before.
# --------------------------------------------------------------------------
"""


import asyncio
import logging
import signal
import siemens_client
import ab_cip_client
import tm221_client
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
    log.info("  Task 2 : Allen-Bradley    EtherNet/IP (CIP) client")
    log.info("  Task 3 : Schneider TM221  Modbus TCP client")
    log.info("  Task 4 : OPC-UA server    → Ignition SCADA")
    tasks = await asyncio.gather(
        siemens_client.run(),
        ab_cip_client.run(),
        tm221_client.run(),
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
