#!/usr/bin/env python3
"""
opta_client.py

MATRIX Testbed — Raspberry Pi Middleware
Arduino Opta Modbus TCP Client

The Arduino Opta running PLC IDE automatically maps IEC 61131-3 output
variables to Modbus coil addresses starting from address 0, in declaration
order. Input variables map to discrete input addresses. No manual register
configuration is required in PLC IDE — but the order in which you declare
variables in PLC IDE determines their Modbus address.

This client:
  - Reads all Conveyor Belt sensor and actuator states
  - Reads the workpiece counter (holding register)
  - Exposes write_coil() for relaying handoff signals from Allen-Bradley
  - Maintains a live state dict readable by opcua_server.py

IMPORTANT — Modbus address convention:
  PLC IDE auto-assigns coil addresses in variable declaration order.
  %QX0.0 → coil 0, %QX0.1 → coil 1, etc.
  %IX0.0 → discrete input 0, %IX0.1 → discrete input 1, etc.
  %MW0   → holding register 0 (16-bit word)

  The address map below MUST match the variable declaration order in your
  PLC IDE program. We will align this when configuring the Opta.


Author : Kananelo Chabeli
"""

import asyncio
import logging
from datetime import datetime
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

# Configuration 

PLC_IP          = "192.168.50.30" 
MODBUS_PORT     = 502
UNIT_ID         = 255   # PLC IDE default unit identifier — do not change

POLL_INTERVAL   = 0.5   # seconds between polling cycles
RECONNECT_DELAY = 5     # seconds between reconnection attempts
POLL_TIMEOUT = 1.0      #Seconds for which the polling of register and data should be done.
# Modbus address maps
# Addresses are 0-based (pymodbus convention).
# PLC IDE variable declaration order determines coil/input addresses.
# Align these maps with your PLC IDE variable list before running.
#
# COIL_MAP      → %QX (output coils) — actuator commands, readable + writable
# INPUT_MAP     → %IX (input discretes) — sensor states, read-only
# REGISTER_MAP  → %MW (memory words) — counters, integers, read/write

COIL_MAP = {
    # address : tag_name                    physical signal
    0: "conveyorBelt",                    # Q5 — conveyor belt motor
    1: "separatorValve",                  # Q6 — separator valve
    2: "sliderMotor",                     # Q3 — motorised pusher
    3: "arduinoActiveIndicator",          # signal IN from Allen-Bradley
}

INPUT_MAP = {
    # address : tag_name                    physical signal
    0: "workpieceOnConveyor",               # B1 (I4) — light barrier, belt entry
    1: "palletReady",                      # B2 (I5) — light barrier, pallet top
    2: "workpieceOnPallet",                    # B3 (I7) — light barrier, pallet present
    3: "sliderInPosition",                     # S3 (I3) — limit switch, pusher home
}

REGISTER_MAP = {
    # # address : tag_name                    description
    # 1: "allenBradleyHandshakeCode",
    # 2: "workpieceCount",                 # running count 0–3 before palletising
    # 3: "totalWorkpieces"
}

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("OPTA_CLIENT")

# Shared state (read by opcua_server.py)

state: dict = {}
for maps in (COIL_MAP, INPUT_MAP, REGISTER_MAP):
    for tag in maps.values():
        state[tag] = None

state["_connected"]   = False
state["_last_update"] = None

# Internal client reference (used by write_coil)

_client: AsyncModbusTcpClient | None = None

# Polling logic

async def _poll(client: AsyncModbusTcpClient):
    """
    Single polling cycle — reads all coils, discrete inputs, and
    holding registers from the Opta, then updates state dict.

    Note on transaction ID mismatch: PLC IDE's Modbus server maintains its
    own transaction counter independently of clients. If pymodbus raises a
    transaction ID warning but the data is correct, it is cosmetic — the
    FramerType.SOCKET framer (default) suppresses the strict check.
    """
    changed = False
    state["_connected"] = True
    # Read output coils (actuator states + handoff flags)
    if COIL_MAP:
        n_coils = max(COIL_MAP.keys()) + 1
        try:
            result = await asyncio.wait_for(client.read_coils(
                address=0, count=n_coils, slave=UNIT_ID),timeout = POLL_TIMEOUT)
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
            result = await asyncio.wait_for(client.read_discrete_inputs(
                address=0, count=n_inputs, slave=UNIT_ID
            ), timeout = POLL_TIMEOUT)
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

    # Read holding registers (workpiece counter)
    if REGISTER_MAP:
        n_regs = max(REGISTER_MAP.keys()) + 1
        try:
            result = await client.read_input_registers(
                address=0, count=n_regs, slave=UNIT_ID
            )
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
        Write a single coil on the Opta.
        Used by main.py to relay the handoff signal from the Allen-Bradley
        when a workpiece has been deposited on the belt.

        Args:
            address : Modbus coil address (0-based, matches COIL_MAP keys)
            value   : True = ON, False = OFF

        Returns:
            True if write succeeded, False otherwise.
    """
    if _client is None or not _client.connected:
        log.error("write_coil called but Opta is not connected")
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
    Write a single holding register on the Opta.
    Useful for resetting the workpiece counter from the SCADA layer.
    """
    if _client is None or not _client.connected:
        log.error("write_register called but Opta is not connected")
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

async def benchmark_read_coil(address=0):
    """
    Fresh Modbus TCP coil read using the existing connection.
    """

    if _client is None:
        raise RuntimeError("Opta Modbus client is not initialized")

    if not _client.connected:
        raise RuntimeError("Opta Modbus client is not connected")

    result = await _client.read_coils(address=address,count=1,slave=UNIT_ID)

    if result.isError():
        raise RuntimeError(
            f"Opta Modbus read failed: {result}"
        )

    return bool(result.bits[0])

# Main connection loop

async def run():
    """
    Connects to Opta Modbus TCP server, polls all mapped addresses
    continuously, and maintains the connection with auto-reconnect.

    Call from main.py:
        asyncio.create_task(opta_client.run())
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
                raise ConnectionError("Could not connect to Opta")

            log.info(f"Connected to Opta at {PLC_IP}:{MODBUS_PORT}")
            state["_connected"] = True

            # Brief pause after connection — allows Opta Modbus server
            # to fully initialise before first read (avoids transaction
            # ID mismatch on immediate first request)
            await asyncio.sleep(1)

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
    print("Running opta_client.py standalone — Ctrl+C to stop")
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


