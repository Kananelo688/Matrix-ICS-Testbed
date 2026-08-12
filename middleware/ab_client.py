#!/usr/bin/env python3
"""
ab_client.py

MATRIX Testbed — Raspberry Pi Middleware
Allen-Bradley Micro820 Modbus TCP Client

The Micro820 does not expose a full EtherNet/IP symbolic tag database the way
a ControlLogix/CompactLogix does. Data exchange therefore uses Modbus TCP,
which is explicitly enabled in CCW's Modbus mapping panel and configured to
map controller variables to specific coil and holding register addresses.

This client:
  - Reads all Transfer Unit sensor states (coils / discrete inputs)
  - Reads all Transfer Unit actuator states (holding registers)
  - Exposes write_coil() for sending handoff signals from other stages
  - Maintains a live state dict readable by opcua_server.py

Modbus register map (must match CCW Modbus mapping configuration exactly):
  See REGISTER_MAP and COIL_MAP below. Addresses are 0-based (pymodbus
  convention). CCW shows 1-based addresses — subtract 1 when cross-checking.


Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import asyncio
import logging
from datetime import datetime
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
import ctypes
# Configuration

PLC_IP          = "192.168.50.20"
MODBUS_PORT     = 502
UNIT_ID         = 1     # Modbus slave/unit ID — default on Micro820

POLL_INTERVAL   = 0.5   # seconds between polling cycles
RECONNECT_DELAY = 5     # seconds between reconnection attempts
POLL_TIMEOUT = 1.5 	# second per read, for it to detect link failure.
# Modbus register map 
# These addresses must match what you configured in CCW's Modbus mapping panel.
# CCW address 1 = pymodbus address 0 (subtract 1 from CCW display value).
#
# COIL_MAP  — Boolean variables mapped as Modbus Coils (read/write, 1-bit)
# INPUT_MAP — Boolean sensor states mapped as Discrete Inputs (read-only, 1-bit)
# REG_MAP   — Integer/status values mapped as Holding Registers (read/write, 16-bit)
#
# Convention used here:
#   Coils 0–9    : handoff signals and actuator command outputs
#   Inputs 0–9   : physical sensor states
#   Registers 0–9: status integers and derived values

COIL_MAP = {
    # address : tag_name
    0: "rotateToConveyor",      # Q1 — motor direction toward turntable
    1: "rotateToTable",       # Q2 — motor direction toward conveyor belt
    2: "vacuumGripper",     # Q8 — vacuum valve on/off
    3: "controllerActiveIndicator",    # signal from AB to indicate controller is active.: "workpiece ready at table"
}

INPUT_MAP = {
    # address : tag_name
    0: "transferUnitAtConveyor",  # S1 (I1) — limit switch at conveyor belt end
    1: "transferUnitAtTurntable", # S2 (I2) — limit switch at turntable end
    2: "turntableInPosition", # S4 - limit switch when table in home position.

}

REG_MAP = {
    # address : tag_name
    0: "siemensHandshakeCode",
    1: "arduinoHandshakeCode",
    2: "transferUnitPositionCode", # 0=unknown, 1=at table, 2=at belt, 3=in transit   
}

# Derived string representation of unit_position_code
_POSITION_LABELS = {ctypes.c_int16(0).value: "UNKNOWN", 
                    ctypes.c_int16(1).value: "AT TABLE", 
                    ctypes.c_int16(2).value: "AT BELT", 
                    ctypes.c_int16(3).value: "IN TRANSIT"}

_SIEMENS_HANDSHAKE_LABELS = {ctypes.c_int16(0).value: "IDLE", 
                             ctypes.c_int16(1).value: "TRANSFER_PART_READY", 
                             ctypes.c_int16(2).value: "TRANSFER_UNIT_DONE"}

_ARDUINO_HANDSHAKE_LABELS = {ctypes.c_int16(0).value: "CONVERYOR_BELT_READY", 
                             ctypes.c_int16(1).value: "TRANSPORT_PART_READY"}
# Logging 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("AB_CLIENT")

# Shared state (read by opcua_server.py) 

state: dict = {}
for maps in (COIL_MAP, INPUT_MAP, REG_MAP):
    for tag in maps.values():
        state[tag] = None

state["unit_position"]  = None   # human-readable string derived from REG 0
state["_connected"]     = False
state["_last_update"]   = None

# Internal client reference (used by write_coil)

_client: AsyncModbusTcpClient | None = None

# Polling logic

async def _poll(client: AsyncModbusTcpClient):
    """
    Single polling cycle — reads all coils, discrete inputs, and
    holding registers, then updates state dict.
    """
    changed = False

    # ── Read coils (actuator states + handoff flags)
    state['_connected'] = True
    if COIL_MAP:
        n_coils = max(COIL_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_coils(address=0, count=n_coils, slave=UNIT_ID), timeout = POLL_TIMEOUT)
            if result.isError():
                log.warning(f"Coil read error: {result}")
            else:
                for addr, tag in COIL_MAP.items():
                    val = result.bits[addr]
                    if state[tag] != val:
                        log.info(f"  {tag:<28} {str(state[tag]):<8} → {val}")
                        state[tag] = val
                        changed = True
        except ModbusException as exc:
            log.warning(f"Coil read exception: {exc}")
            if "not connected" in str(exc).lower():
               state["_connected"] = False
    # ── Read discrete inputs (physical sensor states)
    if INPUT_MAP:
        n_inputs = max(INPUT_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_discrete_inputs(address=0, count=n_inputs, slave=UNIT_ID), timeout = POLL_TIMEOUT)
            if result.isError():
                log.warning(f"Discrete input read error: {result}")
            else:
                for addr, tag in INPUT_MAP.items():
                    val = result.bits[addr]
                    if state[tag] != val:
                        log.info(f"  {tag:<28} {str(state[tag]):<8} → {val}")
                        state[tag] = val
                        changed = True
        except ModbusException as exc:
            log.warning(f"Discrete input read exception: {exc}")
            if "not connected" in str(exc).lower():
                state["_connected"] = False

    # ── Read holding registers (status integers)
    if REG_MAP:
        n_regs = max(REG_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_holding_registers(address=0, count=n_regs, slave=UNIT_ID), timeout = POLL_TIMEOUT)
            if result.isError():
                log.warning(f"Register read error: {result}")
            else:
                for addr, tag in REG_MAP.items():
                    val = result.registers[addr]
                    if state[tag] != val:
                        log.info(f"  {tag:<28} {str(state[tag]):<8} → {val}")
                        state[tag] = val
                        changed = True
                # Derived human-readable position
                code = state.get("unit_position_code", 0)
                state["unit_position"] = _POSITION_LABELS.get(code, "UNKNOWN")
        except ModbusException as exc:
            log.warning(f"Register read exception: {exc}")
            if "not connected" in str(exc).lower():
                state['_connected'] = False

    if changed:
        state["_last_update"] = datetime.now().isoformat()


# Public API 

async def write_coil(address: int, value: bool) -> bool:
    """
    Write a single coil on the Micro820.
    Used by main.py to relay handoff signals from other controllers.

    Args:
        address : Modbus coil address (0-based, matches COIL_MAP keys)
        value   : True = ON, False = OFF

    Returns:
        True if write succeeded, False otherwise.
    """
    if _client is None or not _client.connected:
        log.error("write_coil called but client is not connected")
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


# Main connection loop

async def run():
    """
    Connects to Micro820 Modbus TCP server, polls all mapped addresses
    continuously, and maintains the connection with auto-reconnect.

    Call from main.py:
        asyncio.create_task(ab_client.run())
    """
    global _client

    while True:
        _client = AsyncModbusTcpClient(
            host=PLC_IP,
            port=MODBUS_PORT,
            timeout=5,
            retries=3
        )

        try:
            await _client.connect()
            if not _client.connected:
                raise ConnectionError("Could not connect")

            log.info(f"Connected to Micro820 at {PLC_IP}:{MODBUS_PORT}")
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
    print("Running ab_client.py standalone — Ctrl+C to stop")
    print(f"Target: {PLC_IP}:{MODBUS_PORT}\n")

    async def _test():
        task = asyncio.create_task(run())
        try:
            while True:
                await asyncio.sleep(2)
                print("\n── Current state ──────────────────────")
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
