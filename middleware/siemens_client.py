#!/usr/bin/env python3
"""
siemens_client.py

MATRIX Testbed — Raspberry Pi Middleware
Siemens S7-1200 OPC-UA Client

Connects to the S7-1200's built-in OPC-UA server (requires firmware >= v4.1).
Subscribes to all Turntable namespace tags and maintains a live state dict
that the OPC-UA aggregation server (opcua_server.py) reads and re-publishes
to Ignition SCADA.

Firmware check:
  TIA Portal → Online & Diagnostics → General → Firmware version
  v4.0  → use snap7 fallback (see bottom of this file)
  v4.1+ → this OPC-UA client works

TIA Portal configuration required before this script will connect:
  1. Device properties → OPC UA → Server → Enable OPC UA server ✓
  2. Create a Server Interface and add your Workpieces DB variables to it
  3. Set security policy to None for initial testing (harden later)
  4. Download configuration to PLC

Author : Kananelo Chabeli
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from asyncua import Client, Node, client
from asyncua.common.subscription import DataChangeNotif

# Configurations 

PLC_IP          = "192.168.50.10"
OPC_PORT        = 4840
OPC_URL         = f"opc.tcp://{PLC_IP}:{OPC_PORT}"

# Security: set to "Basic256Sha256" and provide certificate paths for
# production use. "None_" means no security — acceptable for isolated lab.
SECURITY_POLICY = "None_"

RECONNECT_DELAY = 5   # seconds between reconnection attempts
POLL_INTERVAL   = 0.5 # seconds — subscription publishing interval

LIVENESS_INTERVAL = 1 #seconds between reconnection attempts
LIVENESS_TIMEOUT = 0.5 #seconds between subscription publishing interval

# Namespace URI — TIA Portal OPC-UA server uses this URI by default.
# Confirm via UaExpert browser or Wireshark after enabling OPC-UA on PLC.
# Common TIA Portal pattern:
#   "urn:SIMATIC.S7-1200.OPC-UA.Application:PLC_1"
# You may need to browse ns=0;i=2255 (NamespaceArray) to find your index.
NAMESPACE_URI   = "http://ServerInterface"

# Node ID map
# Format: tag_name → OPC-UA NodeId string
# These follow TIA Portal's default naming when you add DB variables to a
# Server Interface. The namespace index (ns=3) is resolved at runtime from
# NAMESPACE_URI above — you do not need to hard-code the index.
#
# Adjust "Workpieces" to match the exact name of your Data Block in TIA Portal.
# If your DB is named "WorkpieceDB", the path is "WorkpieceDB"."magazinePart".
#
# Format in TIA Portal OPC-UA export:
#   ns=<idx>;s="<DBName>"."<VariableName>"

NODE_DEFS = {
    "inPosition": "ns=4;i=5",
    "magazineEmpty": "ns=4;i=6",
    "motorTurntable": "ns=4;i=7",
    "drillActive": "ns=4;i=8",
    "weldActive": "ns=4;i=9",
    "magazinePart": "ns=4;i=10",
    "transferPart": "ns=4;i=11",
    "sliderMagazine": "ns=4;i=12",
    "weldingPart": "ns=4;i=13",
    "drillPart": "ns=4;i=14",
    "siemensStartCommand": "ns=4;i=18",
    "siemensStopCommand": "ns=4;i=19",
    "siemensResetCommand": "ns=4;i=20",
    "workpiecesCount": "ns=4;i=24",
    "peerCommunicationOK": "ns=4;i=25",
    "controllerActive": "ns=4;i=26",
}

# Logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("SIEMENS_CLIENT")

# Shared state (read by opcua_server.py) 

state: dict = {tag: None for tag in NODE_DEFS}
state["_connected"] = False
state["_last_update"] = None

# Subscription handler

class TurntableHandler:
    """
    Called by asyncua whenever a subscribed node value changes.
    Updates the shared state dict so opcua_server.py can re-publish to Ignition.
    """

    def datachange_notification(self, node: Node, val, data: DataChangeNotif):
        # Reverse-lookup tag name from node
        node_id_str = node.nodeid.to_string()
        tag = _node_id_to_tag.get(node_id_str)
        if tag:
            old = state.get(tag)
            state[tag] = val
            state["_last_update"] = datetime.now().isoformat()
            if old != val:
                log.info(f"  {tag:<30} {str(old):<8} → {val}")

    def event_notification(self, event):
        log.debug(f"Event: {event}")

# Internal helpers

# Maps resolved NodeId string → tag name (populated at runtime)
_node_id_to_tag: dict = {}

_active_client: Client | None = None

# async def _resolve_nodes(client: Client) -> dict[str, Node]:
# #     """
# #     Resolves NAMESPACE_URI to its index on this server, then builds
# #     a {tag_name: Node} dict for all entries in NODE_DEFS.
# #     """
#      ns_idx = await client.get_namespace_index(NAMESPACE_URI)
#      log.info(f"Namespace '{NAMESPACE_URI}' → index {ns_idx}")
#      nodes = {}
#      for tag, identifier in NODE_DEFS.items():
#          node_id = f'ns={ns_idx};s={identifier}'
#          node = client.get_node(node_id)
#          nodes[tag] = node
#          _node_id_to_tag[node.nodeid.to_string()] = tag
#          log.debug(f"  Resolved  {tag:<30} ← {node_id}")

#      return nodes

async def _resolve_nodes(client: Client) -> dict[str, Node]:
    """
        Fetches Node objects directly using the fully qualified numeric NodeIds.
    """
    nodes = {}
    for tag, node_id in NODE_DEFS.items():
       node = client.get_node(node_id)
       nodes[tag] = node
       _node_id_to_tag[node.nodeid.to_string()] = tag
       log.debug(f"  Mapped {tag:<30} ← {node_id}")

    log.info(f"Successfully resolved {len(nodes)} nodes.")
    return nodes

async def _read_all(nodes: dict[str, Node]):
    """
    Reads all tag values once synchronously — used for initial population
    of state before subscription callbacks start firing.
    """
    for tag, node in nodes.items():
        try:
            val = await node.read_value()
            state[tag] = val
            log.info(f"  Initial read  {tag:<30} = {val}")
        except Exception as exc:
            log.warning(f"  Could not read {tag} of node {node}: {exc}")

async def write_node(tag:str, value) -> bool:
    """
        Writes a single tag value to the PLC (Use for HMI-issued commands).
    """
    if not state.get('_connected') or _active_client is None:
        log.warning(f"Cannot write {tag}. Not connected to PLC.")
        return False
    
    node_id = NODE_DEFS.get(tag)
    if node_id is None:
        log.warning(f"Cannot write {tag}. Unknown tag")
        return False
    
    try:
        node = _active_client.get_node(node_id)
        await node.write_value(value)
        log.info(f"  Wrote command: {tag:<30} = {value}")
        return True
    except Exception as exc:
        log.error(f"Write failed [{tag}]; {exc}")
        return False
    
# Main connection loop 

async def run():
    """
    Connects to S7-1200 OPC-UA server, subscribes to all turntable tags,
    and maintains the connection indefinitely with auto-reconnect.

    Call this as an asyncio task from main.py:
        asyncio.create_task(siemens_client.run())
    """
    handler = TurntableHandler()

    while True:
        try:
            log.info(f"Connecting to {OPC_URL} ...")
            async with Client(url=OPC_URL) as client:
                log.info("Connected to S7-1200 OPC-UA server")
                state["_connected"] = True
                global _active_client
                _active_client = client

                # Resolve namespace and node IDs
                nodes = await _resolve_nodes(client)

                # Read initial values before subscription fires
                await _read_all(nodes)

                # Subscribe server pushes updates on value change
                subscription = await client.create_subscription(
                    period=int(POLL_INTERVAL * 1000),  # ms
                    handler=handler
                )
                await subscription.subscribe_data_change(list(nodes.values()))
                log.info(f"Subscribed to {len(nodes)} turntable tags")

                # Keep alive asyncua subscription runs in background
                probe_node = next(iter(nodes.values()))
                while True:
                    try:
                       await asyncio.wait_for(probe_node.read_value(), timeout = LIVENESS_TIMEOUT)
                       state["_connected"] = True
                    except (Exception, asyncio.TimeoutError) as exc:
                       state['_connected'] = False
                       log.warning(f"Liveness check failed: {exc}")
                       raise
                    await asyncio.sleep(LIVENESS_INTERVAL)

        except Exception as exc:
            state["_connected"] = False
            log.error(f"Connection lost: {exc}")
            log.info(f"Reconnecting in {RECONNECT_DELAY}s ...")
            await asyncio.sleep(RECONNECT_DELAY)


# Standalone test

if __name__ == "__main__":
    print("Running siemens_client.py standalone — Ctrl+C to stop")
    print(f"Target: {OPC_URL}\n")

    async def _test():
        await run()

    try:
        asyncio.run(_test())
    except KeyboardInterrupt:
        print("\nStopped.")


# ═════════════════════════════════════════════════════════════════════════════
# SNAP7 FALLBACK — use this block if your S7-1200 is firmware v4.0
# (which does not include the OPC-UA server).
#
# Install:  pip install python-snap7
#
# Replace the run() function above with this version.
# ═════════════════════════════════════════════════════════════════════════════
"""
import snap7
from snap7.util import get_bool, get_int

PLC_IP   = "192.168.20.10"
RACK     = 0
SLOT     = 1
DB_NUM   = 1   # adjust to your Workpieces Data Block number

async def run():
    plc = snap7.client.Client()

    while True:
        try:
            plc.connect(PLC_IP, RACK, SLOT)
            log.info(f"Connected to S7-1200 via S7comm (snap7)")
            state["_connected"] = True

            while True:
                # Read process image inputs (1 byte covers I0.0 to I0.7)
                inputs = plc.read_area(snap7.types.Areas.PE, 0, 0, 1)
                state["turntable_in_position"] = get_bool(inputs, 0, 6)  # I0.6 = S4
                state["magazine_empty"]         = not get_bool(inputs, 0, 7)  # I0.7 = B4 (inverted)

                # Read process image outputs
                outputs = plc.read_area(snap7.types.Areas.PA, 0, 0, 2)
                state["motor_turntable"] = get_bool(outputs, 0, 3)  # Q0.3 = Q4
                state["slider_magazine"] = get_bool(outputs, 0, 6)  # Q0.6 = Q7
                state["drill_active"]    = get_bool(outputs, 1, 0)  # Q1.0 = Q9
                state["weld_active"]     = get_bool(outputs, 1, 1)  # Q1.1 = Q10

                # Read Workpieces Data Block (DB1, 5 bytes of BOOL flags)
                db = plc.db_read(DB_NUM, 0, 5)
                state["magazinePart"]         = get_bool(db, 0, 0)
                state["drillingRawPart"]       = get_bool(db, 0, 1)
                state["drillingFinishedPart"]  = get_bool(db, 0, 2)
                state["weldingRawPart"]        = get_bool(db, 0, 3)
                state["weldingFinishedPart"]   = get_bool(db, 0, 4)
                state["transferPart"]          = get_bool(db, 0, 5)
                state["turntable_index"]       = get_int(db, 2)
                state["_last_update"]          = datetime.now().isoformat()

                await asyncio.sleep(0.5)

        except Exception as exc:
            state["_connected"] = False
            log.error(f"S7comm error: {exc}")
            try:
                plc.disconnect()
            except Exception:
                pass
            log.info(f"Reconnecting in {RECONNECT_DELAY}s ...")
            await asyncio.sleep(RECONNECT_DELAY)
"""
