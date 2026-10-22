#!/usr/bin/env python3
"""
ab_cip_client.py

MATRIX Testbed — Raspberry Pi Middleware
Allen-Bradley Micro820 EtherNet/IP (CIP) Client

The Micro820 (2080-LC20-20QWB) is a Micro800-series controller. Although it
has no backplane/slots and no full symbolic tag database upload the way a
ControlLogix/CompactLogix does for program-scoped tags, pycomm3's
LogixDriver DOES support direct symbolic read/write of Global Variables
defined in CCW, using just the IP address as the path. Confirmed working:

pycomm3 is fully synchronous — there is no native asyncio support. To keep
this client plug-and-play with the existing asyncio middleware (main.py /
opcua_server.py), every blocking pycomm3 call is offloaded to a worker
thread via asyncio.to_thread().

This client:
  - Reads all Transfer Unit tags in a single batched CIP request per cycle
  - Exposes write_tag() for sending handoff signals from other stages
  - Maintains a live state dict readable by opcua_server.py (same shape
    and tag names as ab_client.py, so the OPC-UA server needs no changes)

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import asyncio
import logging
from datetime import datetime
from pycomm3 import LogixDriver
import ctypes

# Configuration

PLC_IP          = "192.168.50.20"

POLL_INTERVAL   = 0.5   # seconds between polling cycles
RECONNECT_DELAY = 5     # seconds between reconnection attempts
POLL_TIMEOUT    = 1.5   # seconds per read, to detect link failure

# Tag map
# Keys here are the exact Global Variable names as defined in CCW.
# Values are the internal state-dict keys used elsewhere in the middleware
# (kept identical to ab_client.py's COIL_MAP/INPUT_MAP/REG_MAP tag names so
# opcua_server.py requires no changes when swapping clients).

TAG_MAP = {
    # CCW Global Variable name         : internal tag_name
    "_IO_EM_DO_04":   "rotateToTable",
    "_IO_EM_DO_05":   "rotateToConveyor",
    "_IO_EM_DO_06":   "vacuumGripper",
    "controllerActive": "controllerActiveIndicator",
    "_IO_EM_DI_04":   "transferUnitAtConveyor",
    "_IO_EM_DI_05":   "transferUnitAtTurntable",
    "_IO_EM_DI_06":   "turntableInPosition",
    "SeimensModbusHandshake": "siemensHandshakeCode",
    "SchneiderModbusHandshake": "schneiderHandShakeCode",
    "UnitPositionCode": "unit_position_code",
}

# Tags this client is allowed to write (handoff / command outputs).
# Subset of TAG_MAP — writing to a read-only sensor tag will simply fail
# on the PLC side, but keeping this explicit avoids accidental writes.
WRITABLE_TAGS = {
    "_IO_EM_DO_04":   "rotateToTable",
    "_IO_EM_DO_05":   "rotateToConveyor",
    "_IO_EM_DO_06":   "vacuumGripper",
    "controllerActive": "controllerActiveIndicator",
}

# Derived string representation of unit_position_code (unchanged from ab_client.py)
_POSITION_LABELS = {ctypes.c_int16(0).value: "UNKNOWN",
                    ctypes.c_int16(1).value: "AT TABLE",
                    ctypes.c_int16(2).value: "AT BELT",
                    ctypes.c_int16(3).value: "IN TRANSIT"}

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("AB_CIP_CLIENT")

# Shared state (read by opcua_server.py)

state: dict = {}
for internal_tag in TAG_MAP.values():
    state[internal_tag] = None

state["unit_position"] = None   # human-readable string derived from unit_position_code
state["_connected"]    = False
state["_last_update"]  = None

# Internal driver reference (used by write_tag)

_plc: LogixDriver | None = None

# Blocking pycomm3 calls, run off the event loop via asyncio.to_thread()

def _blocking_connect(ip: str) -> LogixDriver:
    plc = LogixDriver(ip)
    plc.open()
    if not plc.connected:
        raise ConnectionError(f"Could not open CIP connection to {ip}")
    return plc


def _blocking_read_all(plc: LogixDriver, ccw_names: list[str]):
    return plc.read(*ccw_names)


def _blocking_write(plc: LogixDriver, ccw_name: str, value):
    return plc.write((ccw_name, value))


def _blocking_close(plc: LogixDriver):
    plc.close()


# Polling logic

async def _poll(plc: LogixDriver):
    """
    Single polling cycle — batch-reads all mapped Global Variables in one
    CIP Multiple Service Packet request, then updates state dict.
    """
    changed = False
    ccw_names = list(TAG_MAP.keys())

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(_blocking_read_all, plc, ccw_names),
            timeout=POLL_TIMEOUT
        )
        state["_connected"] = True
    except (asyncio.TimeoutError, Exception) as exc:
        log.warning(f"Batch read failed: {exc}")
        state["_connected"] = False
        return

    for ccw_name, tag_result in zip(ccw_names, results):
        internal_tag = TAG_MAP[ccw_name]
        if tag_result.error: #type:ignore
            log.warning(f"  {ccw_name} read error: {tag_result.error}") #type:ignore
            continue
        val = tag_result.value #type:ignore
        if state[internal_tag] != val:
            log.info(f"  {internal_tag:<28} {str(state[internal_tag]):<8} → {val}")
            state[internal_tag] = val
            changed = True

    # Derived human-readable position
    code = state.get("unit_position_code", 0)
    state["unit_position"] = _POSITION_LABELS.get(code, "UNKNOWN")

    if changed:
        state["_last_update"] = datetime.now().isoformat()


# Public API

async def write_tag(internal_tag: str, value) -> bool:
    """
    Write a single Global Variable on the Micro820.
    Used by main.py to relay handoff signals from other controllers.

    Args:
        internal_tag : internal state-dict key (e.g. "vacuumGripper"),
                        must be present in WRITABLE_TAGS
        value         : value to write (type must match the CCW tag's
                        declared data type)

    Returns:
        True if write succeeded, False otherwise.
    """
    if _plc is None or not _plc.connected:
        log.error("write_tag called but CIP client is not connected")
        return False

    ccw_name = WRITABLE_TAGS.get(internal_tag)
    if ccw_name is None:
        log.error(f"write_tag: '{internal_tag}' is not a writable tag")
        return False

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_blocking_write, _plc, ccw_name, value),
            timeout=POLL_TIMEOUT
        )
        if result.error: #type:ignore
            log.warning(f"write_tag({ccw_name}, {value}) → error: {result.error}") #type:ignore
            return False
        log.info(f"write_tag({ccw_name}, {value}) → OK")
        state[internal_tag] = value
        return True
    except Exception as exc:
        log.error(f"write_tag exception: {exc}")
        return False


async def benchmark_read(ccw_name: str = "SchneiderModbusHandshake"):
    """
    Fresh CIP read of a single tag using the existing connection.
    Benchmark-only function. Does not modify state[].
    """
    if _plc is None or not _plc.connected:
        raise RuntimeError("AB CIP client is not connected")

    result = await asyncio.to_thread(_plc.read, ccw_name)
    if result.error: #type:ignore
        raise RuntimeError(f"AB CIP read failed: {result.error}")   #type:ignore

    return result.value #type:ignore


# Main connection loop

async def run():
    """
    Connects to Micro820 via EtherNet/IP (CIP), polls all mapped Global
    Variables continuously, and maintains the connection with auto-reconnect.

    Call from main.py:
        asyncio.create_task(ab_cip_client.run())
    """
    global _plc

    while True:
        try:
            _plc = await asyncio.wait_for(
                asyncio.to_thread(_blocking_connect, PLC_IP),
                timeout=5
            )
            log.info(f"Connected to Micro820 at {PLC_IP} via EtherNet/IP")
            log.info(f"  Product: {_plc.info.get('product_name', 'unknown')}")
            state["_connected"] = True

            while True:
                await _poll(_plc)
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as exc:
            state["_connected"] = False
            log.error(f"Connection lost: {exc}")
            log.info(f"Reconnecting in {RECONNECT_DELAY}s ...")

        finally:
            if _plc is not None:
                try:
                    await asyncio.to_thread(_blocking_close, _plc)
                except Exception:
                    pass

        await asyncio.sleep(RECONNECT_DELAY)


# Standalone test

if __name__ == "__main__":
    print("Running ab_cip_client.py standalone — Ctrl+C to stop")
    print(f"Target: {PLC_IP} (EtherNet/IP)\n")

    async def _test():
        task = asyncio.create_task(run())
        try:
            while True:
                await asyncio.sleep(2)
                print("\n── Current state ───────────")
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