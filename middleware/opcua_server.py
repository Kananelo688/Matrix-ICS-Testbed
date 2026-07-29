"""
opcua_server.py

MATRIX Testbed — Raspberry Pi Middleware
OPC-UA Aggregation Server (Middleware → Ignition SCADA)

Exposes a unified OPC-UA address space under Objects/MATRIX/ with four zones:
  System/        ← middleware health and connectivity
  Turntable/     ← Siemens S7-1200 tags
  TransferUnit/  ← Allen-Bradley Micro820 tags
  Conveyor/      ← Arduino Opta tags

Ignition connects to opc.tcp://<RPi-IP>:4840 as an OPC-UA client.

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import asyncio
import logging
from datetime import datetime, timezone
from asyncua import Server, ua

# Import PLC client modules
try:
    import siemens_client
    import ab_client
    import opta_client
    _STANDALONE = False
except ImportError:
    _STANDALONE = True

# Configuration 

SERVER_ENDPOINT = "opc.tcp://192.168.50.1:4840"
NAMESPACE_URI   = "urn:MATRIX.Middleware.OPC-UA"
SERVER_NAME     = "MATRIX ICS Testbed — Middleware OPC-UA Server"
UPDATE_INTERVAL = 0.5  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("OPC_UA_SERVER")

logging.getLogger("asyncua").setLevel(logging.WARNING)
logging.getLogger("asyncua.server.address_space").setLevel(logging.WARNING)
logging.getLogger("asyncua.server.node_management").setLevel(logging.WARNING)
# ── Mock states for standalone mode ──────────────────────────────────────────

if _STANDALONE:
    log.warning("Standalone mode — using mock state dicts")

    class _M:
        state = {}

    siemens_client = _M()
    siemens_client.state = {
        "turntableInPosition": False, "magazineEmpty": False,
        "motorTurntable": False, "drillActive": False, "weldActive": False,
        "magazinePart": False, "transferPart": False, "sliderMagazine": False,
        "weldingPart": False, "drillPart": False,
        "siemensStart": False, "siemensStop": False, "siemensReset": False,
        "siemensCycleCount": 0, "siemensPeerCommunicationOk": False,
        "siemensHealthy": False, "_connected": False,
    }

    ab_client = _M()
    ab_client.state = {
        "rotateToConveyor": False, "rotateToTable": False,
        "vacuumGripper": False, "controllerActiveIndicator": False,
        "transferUnitAtConveyor": False, "transferUnitAtTurntable": False,
        "turntableInPosition": False,
        "siemensHandshakeCode": 0, "arduinoHandshakeCode": 0,
        "unit_position_code": 0, "_connected": False,
    }

    opta_client = _M()
    opta_client.state = {
        "conveyorBelt": False, "separatorValve": False,
        "sliderMotor": False, "arduinoActiveIndicator": False,
        "workpieceOnConveyor": False, "palletReady": False,
        "workpieceOnPallet": False, "sliderInPosition": False,
        "_connected": False,
    }

#  Node definitions 
# (state_key, display_name, VariantType, writable, description)

SYSTEM_NODES = [
    ("siemens_connected",  "Siemens Connected",     ua.VariantType.Boolean, False, "S7-1200 OPC-UA connection status"),
    ("ab_connected",       "AB Connected",          ua.VariantType.Boolean, False, "Micro820 Modbus TCP connection status"),
    ("opta_connected",     "Opta Connected",        ua.VariantType.Boolean, False, "Opta Modbus TCP connection status"),
    ("middleware_uptime",  "Middleware Uptime",     ua.VariantType.String,  False, "Time since middleware started (HH:MM:SS)"),
    ("last_update",        "Last Update",           ua.VariantType.String,  False, "ISO timestamp of last state push"),
]

TURNTABLE_NODES = [
    # Process image inputs
    ("turntableInPosition",         "Turntable In Position",          ua.VariantType.Boolean, False, "S4 — rotary table aligned with stations"),
    ("magazineEmpty",               "Magazine Empty",                 ua.VariantType.Boolean, False, "B4 — True = no workpiece in magazine"),
    ("motorTurntable",              "Motor Turntable",                ua.VariantType.Boolean, False, "Q4 — turntable rotation motor active"),
    ("drillActive",                 "Drill Active",                   ua.VariantType.Boolean, False, "Q9 — drilling station motor (3s)"),
    ("weldActive",                  "Weld Active",                    ua.VariantType.Boolean, False, "Q10 — welding station lamp (5s)"),
    
    # Workpiece management DB flags
    ("magazinePart",                "Magazine Part",                  ua.VariantType.Boolean, False, "DB — nest 1 (magazine) occupied"),
    ("transferPart",                "Transfer Part Ready",            ua.VariantType.Boolean, False, "DB — nest 4 finished workpiece ready for pickup"),
    ("sliderMagazine",              "Slider Magazine",                ua.VariantType.Boolean, False, "Q7 — magazine slider valve active"),
    ("weldingPart",                 "Welding Part",                   ua.VariantType.Boolean, False, "DB — nest 3 has workpiece"),
    ("drillPart",                   "Drill Part",                     ua.VariantType.Boolean, False, "DB — nest 2 has workpiece"),
    
    # Commands (writable from Ignition)
    ("siemensStart",                "Siemens Start Command",          ua.VariantType.Boolean, True,  "Start command — write True from HMI to start cycle"),
    ("siemensStop",                 "Siemens Stop Command",           ua.VariantType.Boolean, True,  "Stop command — write True from HMI to stop"),
    ("siemensReset",                "Siemens Reset Command",          ua.VariantType.Boolean, True,  "Reset command — write True from HMI to reset faults"),
   
    # Diagnostics
    ("siemensCycleCount",           "Siemens Cycle Count",            ua.VariantType.Int16,   False, "Total completed turntable cycles"),
    ("siemensPeerCommunicationOk",  "Siemens Peer Comm OK",           ua.VariantType.Boolean, False, "Level 1 Modbus TCP peer link healthy"),
    ("siemensHealthy",              "Siemens Healthy",                ua.VariantType.Boolean, False, "Controller self-diagnostic flag"),
]

TRANSFER_UNIT_NODES = [
    # Output coils
    ("rotateToConveyor",            "Rotate To Conveyor",             ua.VariantType.Boolean, False, "Q1 — transfer unit motor toward conveyor belt"),
    ("rotateToTable",               "Rotate To Table",                ua.VariantType.Boolean, False, "Q2 — transfer unit motor toward turntable"),
    ("vacuumGripper",               "Vacuum Gripper",                 ua.VariantType.Boolean, False, "Q8 — vacuum valve active (gripping workpiece)"),
    ("controllerActiveIndicator",   "Controller Active Indicator",    ua.VariantType.Boolean, False, "Micro820 heartbeat indicator"),
    # Discrete inputs
    ("transferUnitAtConveyor",      "Transfer Unit At Conveyor",      ua.VariantType.Boolean, False, "S1 — limit switch at conveyor belt end"),
    ("transferUnitAtTurntable",     "Transfer Unit At Turntable",     ua.VariantType.Boolean, False, "S2 — limit switch at turntable end"),
    ("turntableInPosition",         "Turntable In Position (AB)",     ua.VariantType.Boolean, False, "S4 — turntable home position (AB-side read)"),
    # Holding registers
    ("siemensHandshakeCode",        "Siemens Handshake Code",         ua.VariantType.Int16,   False, "Handshake register read from Siemens"),
    ("arduinoHandshakeCode",        "Arduino Handshake Code",         ua.VariantType.Int16,   False, "Handshake register read from Opta"),
    ("transferUnitPositionCode",    "Unit Position Code",             ua.VariantType.Int16,   False, "0=Unknown 1=AtTable 2=AtBelt 3=InTransit"),
]

CONVEYOR_NODES = [
    # Output coils
    ("conveyorBelt",                "Conveyor Belt Motor",            ua.VariantType.Boolean, False, "Q5 — belt drive motor active"),
    ("separatorValve",              "Separator Valve",                ua.VariantType.Boolean, False, "Q6 — separator valve active"),
    ("sliderMotor",                 "Slider Motor",                   ua.VariantType.Boolean, False, "Q3 — motorised pusher active"),
    ("arduinoActiveIndicator",      "Arduino Active Indicator",       ua.VariantType.Boolean, False, "Opta heartbeat indicator"),
    # Discrete inputs
    ("workpieceOnConveyor",         "Workpiece On Conveyor",          ua.VariantType.Boolean, False, "B1 — light barrier; workpiece on belt"),
    ("palletReady",                 "Pallet Ready",                   ua.VariantType.Boolean, False, "B2 — light barrier; pallet present"),
    ("workpieceOnPallet",           "Workpiece On Pallet",            ua.VariantType.Boolean, False, "B3 — light barrier; workpieces on pallet"),
    ("sliderInPosition",            "Slider In Position",             ua.VariantType.Boolean, False, "S3 — pusher slider at home position"),
]

# Source map — links each node tag to its client state dict 
# Built at runtime after imports resolve.

def _build_source_map() -> dict:
    src = {}
    for tag, *_ in TURNTABLE_NODES:
        src[tag] = (siemens_client.state, tag)
    for tag, *_ in TRANSFER_UNIT_NODES:
        src[tag] = (ab_client.state, tag)
    for tag, *_ in CONVEYOR_NODES:
        src[tag] = (opta_client.state, tag)
    # System nodes
    src["siemens_connected"] = (siemens_client.state, "_connected")
    src["ab_connected"]      = (ab_client.state,      "_connected")
    src["opta_connected"]    = (opta_client.state,    "_connected")
    return src

# Build OPC-UA address space 

async def _build_address_space(server: Server, ns: int) -> dict:
    objects     = server.nodes.objects
    matrix_node = await objects.add_object(ns, "MATRIX")
    nodes       = {}

    async def _add_zone(parent, zone_name: str, defs: list):
        folder = await parent.add_object(ns, zone_name)
        for tag, display, vtype, writable, desc in defs:
            default = (
                False if vtype == ua.VariantType.Boolean
                else 0 if vtype == ua.VariantType.Int16
                else ""
            )
            var = await folder.add_variable(ns, display, default, vtype)
            if writable:
                await var.set_writable()
            await var.write_attribute(
                ua.AttributeIds.Description,
                ua.DataValue(ua.Variant(ua.LocalizedText(desc)))
            )
            nodes[tag] = var

    await _add_zone(matrix_node, "System",       SYSTEM_NODES)
    await _add_zone(matrix_node, "Turntable",    TURNTABLE_NODES)
    await _add_zone(matrix_node, "TransferUnit", TRANSFER_UNIT_NODES)
    await _add_zone(matrix_node, "Conveyor",     CONVEYOR_NODES)

    total = len(nodes)
    log.info(
        f"Address space: {len(SYSTEM_NODES)} system | "
        f"{len(TURNTABLE_NODES)} turntable | "
        f"{len(TRANSFER_UNIT_NODES)} transfer | "
        f"{len(CONVEYOR_NODES)} conveyor | "
        f"{total} total nodes"
    )
    return nodes

# Type coercion helper 

_ALL_NODES = SYSTEM_NODES + TURNTABLE_NODES + TRANSFER_UNIT_NODES + CONVEYOR_NODES

def _coerce(tag: str, raw):
    for nd in _ALL_NODES:
        if nd[0] == tag:
            vtype = nd[2]
            if vtype == ua.VariantType.Boolean:
                return bool(raw)
            elif vtype == ua.VariantType.Int16:
                return ua.Variant(int(raw) if raw is not None else 0, ua.VariantType.Int16)
            elif vtype == ua.VariantType.String:
                return ua.Variant(str(raw) if raw is not None else "", ua.VariantType.String)
    return raw

# Update loop

async def _update_loop(nodes: dict, start_time: datetime):
    source_map = _build_source_map()
    log.info(f"Update loop running — {UPDATE_INTERVAL}s interval")

    while True:
        try:
            now    = datetime.now(timezone.utc)
            uptime = str(now - start_time).split(".")[0]

            await nodes["middleware_uptime"].write_value(uptime)
            await nodes["last_update"].write_value(now.isoformat())

            for tag, node in nodes.items():
                if tag in ("middleware_uptime", "last_update"):
                    continue
                src_dict, src_key = source_map.get(tag, ({}, None))
                if src_key is None:
                    continue
                raw = src_dict.get(src_key)
                if raw is None:
                    continue
                try:
                    await node.write_value(_coerce(tag, raw))
                except Exception as exc:
                    log.warning(f"Node write failed [{tag}]: {exc}")

        except Exception as exc:
            log.error(f"Update loop error: {exc}")

        await asyncio.sleep(UPDATE_INTERVAL)

# Main 

async def run():
    server = Server()
    await server.init()
    server.set_endpoint(SERVER_ENDPOINT)
    server.set_server_name(SERVER_NAME)
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

    ns = await server.register_namespace(NAMESPACE_URI)
    log.info(f"Namespace '{NAMESPACE_URI}' → index {ns}")

    nodes      = await _build_address_space(server, ns)
    start_time = datetime.now(timezone.utc)

    async with server:
        log.info(f"OPC-UA server listening at {SERVER_ENDPOINT}")
        log.info("Connect Ignition OPC-UA driver to this endpoint.")
        await _update_loop(nodes, start_time)


if __name__ == "__main__":
    print(f"opcua_server.py — {'STANDALONE (mock)' if _STANDALONE else 'LIVE'}")
    print(f"Endpoint: {SERVER_ENDPOINT}")
    print("Browse with UaExpert: opc.tcp://localhost:4840\n")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
