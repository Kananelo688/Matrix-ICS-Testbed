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

Author : Kananelo Chabeli

# ==========================================================================
# SUMMARY OF CHANGES (2026-10-22) — all additive; read/poll path untouched.
#   [TM-1] NO change to the poll logic. In particular the discrete-input read
#          via read_coils() is KEPT AS-IS: the EcoStruxure mapping exposes
#          those sensors through the coil table and is confirmed working.
#          A comment is added so nobody "fixes" it to read_discrete_inputs()
#          and breaks a working mapping.
#   [TM-2] write_tag(tag, value): a thin wrapper over write_coil() keyed by
#          INTERNAL tag name, so opcua_server.py can forward SCADA actuator
#          writes uniformly (same call shape as the Siemens/AB clients).
#   [TM-3] benchmark_write(): writes a counter to a BENIGN SCRATCH holding
#          register to time the write path without moving an actuator.
#   [TM-4] verify_write(): optional read-back confirmation, kept out of any
#          timed write path.
# write_coil()/write_register() bodies are unchanged.
# ==========================================================================
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

# --------------------------------------------------------------------------
# CHANGE [TM-3]: benign scratch holding register for WRITE-path benchmarking.
# Map an UNWIRED holding register in EcoStruxure used only for benchmarking.
# benchmark_write() writes a counter to it. Leave as None until mapped;
# benchmark_write() then logs and returns False (read-path benchmark still
# works).
# --------------------------------------------------------------------------
BENCHMARK_SCRATCH_REG = None   # e.g. 100

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

# --------------------------------------------------------------------------
# CHANGE [TM-2]: internal-tag → coil-address map for SCADA-writable actuators.
# Derived from COIL_MAP, restricted to the physical outputs (the TM221 heartbeat
# "tm221ActiveIndicator" is intentionally excluded — read-only to SCADA).
# Used by write_tag() so the OPC-UA server can forward writes by tag name.
# --------------------------------------------------------------------------
WRITABLE_TAGS = {
    "sliderMotor":    10,
    "conveyorBelt":   11,
    "separatorValve": 12,
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
    # NOTE [TM-1]: this intentionally uses read_coils(), NOT read_discrete_inputs().
    # The TM221's EcoStruxure Modbus mapping exposes these sensors through the
    # coil table, and this is confirmed working. Do not "correct" it.
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


# --------------------------------------------------------------------------
# CHANGE [TM-2]: tag-based write wrapper so the OPC-UA server can forward SCADA
# actuator writes uniformly (siemens_client.write_node / ab_cip_client.write_tag
# / tm221_client.write_tag all take (identifier, value)). Thin wrapper over
# write_coil() — no new Modbus logic.
# --------------------------------------------------------------------------
async def write_tag(internal_tag: str, value) -> bool:
    address = WRITABLE_TAGS.get(internal_tag)
    if address is None:
        log.error(f"write_tag: '{internal_tag}' is not a writable TM221 tag")
        return False
    return await write_coil(address, bool(value))


async def benchmark_read_coil(address: int = 0):
    """
    	Fresh Modbus TCP coil read using the existing connection.
	It is used for benchmarking the latency between middleware and the PLCs.
    """
    if _client is None:
        raise RuntimeError("TM221 Modbus client is not initialized")

    if not _client.connected:
        raise RuntimeError("TM221 Modbus client is not connected")

    result = await _client.read_coils(address=address, count=1, slave=UNIT_ID)

    if result.isError():
        raise RuntimeError(f"TM221 Modbus read failed: {result}")

    return bool(result.bits[0])


# --------------------------------------------------------------------------
# CHANGE [TM-3]: fresh Modbus WRITE to the benign scratch holding register, for
# timing the SCADA→middleware→PLC write path. Returns True on success, False if
# BENCHMARK_SCRATCH_REG is unset; raises on a real Modbus error. Does not move
# any actuator.
# --------------------------------------------------------------------------
async def benchmark_write(value) -> bool:
    if _client is None or not _client.connected:
        raise RuntimeError("TM221 Modbus client is not connected")
    if BENCHMARK_SCRATCH_REG is None:
        log.warning("benchmark_write skipped: BENCHMARK_SCRATCH_REG not configured")
        return False
    result = await _client.write_register(
        address=BENCHMARK_SCRATCH_REG, value=int(value), slave=UNIT_ID
    )
    if result.isError():
        raise RuntimeError(f"TM221 benchmark write failed: {result}")
    return True


# --------------------------------------------------------------------------
# CHANGE [TM-4]: optional read-back verification of a written coil. Separate
# from write_tag()/write_coil() so it is never inside a timed write.
# --------------------------------------------------------------------------
async def verify_write(internal_tag, expected, retries: int = 3, delay: float = 0.1) -> bool:
    address = WRITABLE_TAGS.get(internal_tag)
    if address is None or _client is None:
        return False
    for _ in range(retries):
        try:
            result = await _client.read_coils(address=address, count=1, slave=UNIT_ID)
            if (not result.isError()) and bool(result.bits[0]) == bool(expected):
                return True
        except Exception:
            pass
        await asyncio.sleep(delay)
    return False


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
