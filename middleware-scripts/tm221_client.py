#!/usr/bin/env python3
"""
tm221_client.py

MATRIX Testbed — Raspberry Pi Middleware
Schneider TM221CE16R Modbus TCP Client

This client replaces the previous Arduino Opta stage on Modbus TCP
(see opta_client.py, now retired in favour of ab_cip_client.py using
EtherNet/IP for the Micro820). The TM221CE16R takes over the Conveyor
Belt stage role, communicating with the middleware over Modbus TCP.

This client:
  - Reads all Conveyor Belt sensor and actuator states
  - Exposes write_coil() / write_register() for relaying handoff signals
  - Maintains a live state dict readable by opcua_server.py

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import asyncio
import logging
from datetime import datetime
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

# Configuration

PLC_IP          = "192.168.50.50"
MODBUS_PORT     = 502
UNIT_ID         = 1     # confirm against EcoStruxure Machine Expert project settings

POLL_INTERVAL   = 0.5   # seconds between polling cycles
RECONNECT_DELAY = 5     # seconds between reconnection attempts
POLL_TIMEOUT    = 1.0   # seconds per read, to detect link failure

# Modbus register map — PLACEHOLDER
# Fill these in exactly as configured in EcoStruxure Machine Expert's
# Modbus TCP mapping for the TM221CE16R. Addresses are 0-based.
#
# COIL_MAP     — Boolean variables mapped as Modbus Coils (read/write, 1-bit)
# INPUT_MAP    — Boolean sensor states mapped as Discrete Inputs (read-only, 1-bit)
# REGISTER_MAP — Integer/status values mapped as Holding Registers (read/write, 16-bit)

COIL_MAP = {
    # address : tag_name
    10: "sliderMotor",
    11: "conveyorBelt",
    12: "separatorValve",
    1: "tm221ActiveIndicator",
}

INPUT_MAP = {
    # address : tag_name
    20: "sliderInPosition",
    21: "workpieceOnConveyor",
    22: "workpieceOnPallet",
    23: "palletReady", 
}

REGISTER_MAP = {
    # address : tag_name
     0: "workpieceCount",
    #  0: "allenBradleyHandshakeCode",
    # 2: "totalWorkpieces"
}

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("TM221_CLIENT")

# Shared state (read by opcua_server.py)

state: dict = {}
for maps in (COIL_MAP, INPUT_MAP, REGISTER_MAP):
    for tag in maps.values():
        state[tag] = None

state["_connected"]   = False
state["_last_update"] = None

# Internal client reference (used by write_coil / write_register)

_client: AsyncModbusTcpClient | None = None

# Polling logic

async def _poll(client: AsyncModbusTcpClient):
    """
    Single polling cycle — reads all coils, discrete inputs, and
    holding registers from the TM221, then updates state dict.
    """
    changed = False
    state["_connected"] = True

    # Read output coils (actuator states + handoff flags)
    if COIL_MAP:
        n_coils = max(COIL_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_coils(
                address=0, count=n_coils, slave=UNIT_ID), timeout=POLL_TIMEOUT)
            if result.isError():
                log.warning(f"Coil read error: {result}")
            else:
                for addr, tag in COIL_MAP.items():
                    val = bool(result.bits[addr])
                    if state[tag] != val:
                        log.info(f"  {tag:<28} {str(state[tag]):<8} → {val}")
                        state[tag] = val
                        changed = True
        except ModbusException as exc:
            log.warning(f"Coil read exception: {exc}")
            if "not connected" in str(exc).lower():
                state["_connected"] = False

    # Read discrete inputs (physical sensor states)
    if INPUT_MAP:
        n_inputs = max(INPUT_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_coils(
                address=0, count=n_inputs, slave=UNIT_ID), timeout=POLL_TIMEOUT)
            if result.isError():
                log.warning(f"Discrete input read error: {result}")
            else:
                for addr, tag in INPUT_MAP.items():
                    val = bool(result.bits[addr])
                    if state[tag] != val:
                        log.info(f"  {tag:<28} {str(state[tag]):<8} → {val}")
                        state[tag] = val
                        changed = True
        except ModbusException as exc:
            log.warning(f"Discrete input exception: {exc}")
            if "not connected" in str(exc).lower():
                state["_connected"] = False

    # Read holding registers
    if REGISTER_MAP:
        n_regs = max(REGISTER_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_holding_registers(
                address=0, count=n_regs, slave=UNIT_ID), timeout=POLL_TIMEOUT)
            if result.isError():
                log.warning(f"Register read error: {result}")
            else:
                for addr, tag in REGISTER_MAP.items():
                    val = result.registers[addr]
                    if state[tag] != val:
                        log.info(f"  {tag:<28} {str(state[tag]):<8} → {val}")
                        state[tag] = val
                        changed = True
        except ModbusException as exc:
            log.warning(f"Register read exception: {exc}")
            if "not connected" in str(exc).lower():
                state["_connected"] = False

    if changed:
        state["_last_update"] = datetime.now().isoformat()


# Public API

async def write_coil(address: int, value: bool) -> bool:
    """
    Write a single coil on the TM221.
    Used by main.py to relay handoff signals from other controllers.

    Args:
        address : Modbus coil address (0-based, matches COIL_MAP keys)
        value   : True = ON, False = OFF

    Returns:
        True if write succeeded, False otherwise.
    """
    if _client is None or not _client.connected:
        log.error("write_coil called but TM221 is not connected")
        return False

    tag = COIL_MAP.get(address, f"coil_{address}")
    try:
        result = await _client.write_coil(
            address=address, value=value, slave=UNIT_ID
        )
        if result.isError():
            log.warning(f"write_coil({tag}, {value}) → error: {result}")
            return False
        log.info(f"write_coil({tag}, {value}) → OK")
        state[tag] = value
        return True
    except ModbusException as exc:
        log.error(f"write_coil exception: {exc}")
        return False


async def write_register(address: int, value: int) -> bool:
    """
    Write a single holding register on the TM221.
    """
    if _client is None or not _client.connected:
        log.error("write_register called but TM221 is not connected")
        return False

    tag = REGISTER_MAP.get(address, f"reg_{address}")
    try:
        result = await _client.write_register(
            address=address, value=value, slave=UNIT_ID
        )
        if result.isError():
            log.warning(f"write_register({tag}, {value}) → error: {result}")
            return False
        log.info(f"write_register({tag}, {value}) → OK")
        state[tag] = value
        return True
    except ModbusException as exc:
        log.error(f"write_register exception: {exc}")
        return False


async def benchmark_read_coil(address: int = 0):
    """
    Fresh Modbus TCP coil read using the existing connection.
    """
    if _client is None:
        raise RuntimeError("TM221 Modbus client is not initialized")

    if not _client.connected:
        raise RuntimeError("TM221 Modbus client is not connected")

    result = await _client.read_coils(address=address, count=1, slave=UNIT_ID)

    if result.isError():
        raise RuntimeError(f"TM221 Modbus read failed: {result}")

    return bool(result.bits[0])


# Main connection loop

async def run():
    """
    Connects to TM221 Modbus TCP server, polls all mapped addresses
    continuously, and maintains the connection with auto-reconnect.

    Call from main.py:
        asyncio.create_task(tm221_client.run())
    """
    global _client

    while True:
        _client = AsyncModbusTcpClient(
            host=PLC_IP,
            port=MODBUS_PORT,
            timeout=10,
            retries=3
        )

        try:
            await _client.connect()
            if not _client.connected:
                raise ConnectionError("Could not connect to TM221")

            log.info(f"Connected to TM221 at {PLC_IP}:{MODBUS_PORT}")
            state["_connected"] = True

            while True:
                await _poll(_client)
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as exc:
            state["_connected"] = False
            log.error(f"Connection lost: {exc}")
            log.info(f"Reconnecting in {RECONNECT_DELAY}s ...")

        finally:
            try:
                _client.close()
            except Exception:
                pass

        await asyncio.sleep(RECONNECT_DELAY)


# Standalone test

if __name__ == "__main__":
    print("Running tm221_client.py standalone — Ctrl+C to stop")
    print(f"Target: {PLC_IP}:{MODBUS_PORT}  Unit ID: {UNIT_ID}\n")

    async def _test():
        task = asyncio.create_task(run())
        try:
            while True:
                await asyncio.sleep(2)
                print("\n-------------Current state ------------- ")
                for k, v in state.items():
                    print(f"  {k:<30} {v}")
        except asyncio.CancelledError:
            pass
        finally:
            task.cancel()

    try:
        asyncio.run(_test())
    except KeyboardInterrupt:
        print("\nStopped.")