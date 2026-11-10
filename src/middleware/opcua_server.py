#!/usr/bin/env python3
"""
opcua_server.py

MATRIX Testbed — Raspberry Pi Middleware
OPC-UA Aggregation Server (Middleware → Ignition SCADA)

Exposes a unified OPC-UA address space under Objects/MATRIX/ with four zones:
  System/        ← middleware health and connectivity
  Turntable/     ← Siemens S7-1200 tags
  TransferUnit/  ← Allen-Bradley Micro820 tags (EtherNet/IP)
  Conveyor/      ← Schneider TM221 tags (Modbus TCP)

Ignition connects to opc.tcp://<RPi-IP>:4840 as an OPC-UA client.

Author : MATRIX / Intelligent Connectivity Group — UCT

# ==========================================================================
# SUMMARY OF CHANGES (2026-10-22)
#   [SRV-1] All physical ACTUATOR nodes are now writable (TransferUnit +
#           Conveyor outputs; Siemens outputs were already writable). Sensors
#           and heartbeats stay read-only. This is the address-space half of
#           "control every actuator from SCADA".
#   [SRV-2] The XSS "exploit" node is now OFF by default, gated behind
#           ENABLE_EXPLOIT_NODES. The normal control/research build is clean.
#   [SRV-3] Server-side security is now configurable (SERVER_SECURITY_MODE).
#           Default is NoSecurity — byte-for-byte the old behaviour.
#   [SRV-4] Write-forwarding is generalised from the Siemens-only, two-command
#           hack to a single map covering every writable actuator + command,
#           routed to the correct client. It also FIXES a clobber race that
#           made the old mechanism unusable for level actuators (details at the
#           _handle_command_writes docstring).
#   [SRV-5] A parallel WRITE-path benchmark interface (Request/Response nodes +
#           loop) is added next to the existing READ-path one, timing writes to
#           each client's benign scratch tag.
#   [SRV-6] run() tidied: the confusing #TO-DO toggle comments and the dead
#           commented-out single-loop line were removed. run() keeps running
#           BOTH the update loop and the benchmark loop, exactly as before.
# The read/aggregate/update behaviour and the existing read-echo benchmark are
# otherwise unchanged.
# ==========================================================================
"""

import asyncio
import logging
from datetime import datetime, timezone
from asyncua import Server, ua
from asyncua.server.binary_server_asyncio import OPCUAProtocol
#Logs every client that connects to our Server
orig_connection_made = OPCUAProtocol.connection_made

# Import PLC client modules
try:
    import siemens_client
    import ab_cip_client
    import tm221_client
    _STANDALONE = False
except ImportError:
    _STANDALONE = True

# Configuration 

SERVER_ENDPOINT = "opc.tcp://192.168.100.10:4840"
NAMESPACE_URI   = "urn:MATRIX.Middleware.OPC-UA"
SERVER_NAME     = "MATRIX ICS Testbed — Middleware OPC-UA Server"
UPDATE_INTERVAL = 0.5  # seconds

# --------------------------------------------------------------------------
# CHANGE [SRV-2]: the XSS "exploit" node is only added when this is True.
# Keep it False for every normal control/logging/experiment run. Set it True
# ONLY for the specific experiment that probes how Ignition handles a hostile
# string value delivered through an OPC-UA node.
# --------------------------------------------------------------------------
ENABLE_EXPLOIT_NODES = False

# --------------------------------------------------------------------------
# CHANGE [SRV-3]: server-side OPC-UA security (default = unauthenticated).
#   "none"     → NoSecurity, anonymous. DEFAULT. Identical to old behaviour.
#   "userpass" → Basic256Sha256 + username/password (SERVER_USERS).
#   "cert"     → Basic256Sha256 with the server cert/key below.
# The "userpass"/"cert" branches are a documented STARTING POINT: the exact
# asyncua user-manager / certificate API varies by library version, so validate
# them against your installed asyncua when you enable authentication. The
# default "none" path is the same single call the server used before.
# --------------------------------------------------------------------------
SERVER_SECURITY_MODE = "none"
SERVER_USERS         = {"scada": "changeme"}   # used only when mode == "userpass"
SERVER_CERT          = None                    # path to server cert (mode == "cert")
SERVER_PRIVATE_KEY   = None                    # path to server private key (mode == "cert")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("OPC_UA_SERVER")

logging.getLogger("asyncua").setLevel(logging.WARNING)
logging.getLogger("asyncua.server.address_space").setLevel(logging.WARNING)
logging.getLogger("asyncua.server.node_management").setLevel(logging.WARNING)
# Mock states for standalone mode 

if _STANDALONE:
    log.warning("Standalone mode — using mock state dicts")

    class _M:
        state = {}

    siemens_client = _M()
    siemens_client.state = {
        "inPosition": False, "magazineEmpty": False,
        "motorTurntable": False, "drillActive": False, "weldActive": False,
        "magazinePart": False, "transferPart": False, "sliderMagazine": False,
        "weldingPart": False, "drillPart": False,
        "siemensStart": False, "siemensStop": False, "siemensReset": False,
        "siemensCycleCount": 0, "siemensPeerCommunicationOk": False,
        "siemensHealthy": False, "_connected": False,
    }

    ab_cip_client = _M()
    ab_cip_client.state = {
        "rotateToConveyor": False, "rotateToTable": False,
        "vacuumGripper": False, "controllerActiveIndicator": False,
        "transferUnitAtConveyor": False, "transferUnitAtTurntable": False,
        "turntableInPosition": False,
        "siemensHandshakeCode": 0, "schneiderHandShakeCode": 0,
        "unit_position_code": 0, "_connected": False,
    }

    tm221_client = _M()
    tm221_client.state = {
        "conveyorBelt": False, "separatorValve": False,
        "sliderMotor": False, "tm221ActiveIndicator": False,
        "workpieceOnConveyor": False, "palletReady": False,
        "workpieceOnPallet": False, "sliderInPosition": False,
        "_connected": False,
    }

#  Node definitions
# (state_key, display_name, VariantType, writable, description)

SYSTEM_NODES = [
    ("siemens_connected",  "Siemens Connected",     ua.VariantType.Boolean, False, "S7-1200 OPC-UA connection status"),
    ("ab_connected",       "AB Connected",          ua.VariantType.Boolean, False, "Micro820 EtherNet/IP (CIP) connection status"),
    ("tm221_connected",    "TM221 Connected",       ua.VariantType.Boolean, False, "TM221 Modbus TCP connection status"),
    ("middleware_uptime",  "Middleware Uptime",     ua.VariantType.String,  False, "Time since middleware started (HH:MM:SS)"),
    ("last_update",        "Last Update",           ua.VariantType.String,  False, "ISO timestamp of last state push"),
]

TURNTABLE_NODES = [
    # Process image inputs
    ("inPosition",         	    "Turntable In Position",          ua.VariantType.Boolean, False, "S4 — rotary table aligned with stations"),
    ("magazineEmpty",               "Magazine Empty",                 ua.VariantType.Boolean, False, "B4 — True = no workpiece in magazine"),
    ("motorTurntable",              "Motor Turntable",                ua.VariantType.Boolean, True,  "Q4 — turntable rotation motor active"),
    ("drillActive",                 "Drill Active",                   ua.VariantType.Boolean, True, "Q9 — drilling station motor (3s)"),
    ("weldActive",                  "Weld Active",                    ua.VariantType.Boolean, True, "Q10 — welding station lamp (5s)"),

    # Workpiece management DB flags
    ("magazinePart",                "Magazine Part",                  ua.VariantType.Boolean, False, "DB — nest 1 (magazine) occupied"),
    ("transferPart",                "Transfer Part Ready",            ua.VariantType.Boolean, False, "DB — nest 4 finished workpiece ready for pickup"),
    ("sliderMagazine",              "Slider Magazine",                ua.VariantType.Boolean, True, "Q7 — magazine slider valve active"),
    ("weldingPart",                 "Welding Part",                   ua.VariantType.Boolean, False, "DB — nest 3 has workpiece"),
    ("drillPart",                   "Drill Part",                     ua.VariantType.Boolean, False, "DB — nest 2 has workpiece"),

    # Commands (writable from Ignition)
    ("siemensStartCommand",                "Siemens Start Command",          ua.VariantType.Boolean, True,  "Start command — write True from HMI to start cycle"),
    
    #These commands are not used ( Not needed for this Testbed ) but are left here for future use if needed
    # ("siemensStopCommand",                 "Siemens Stop Command",           ua.VariantType.Boolean, True,  "Stop command — write True from HMI to stop"),
    # ("siemensResetCommand",                "Siemens Reset Command",          ua.VariantType.Boolean, True,  "Reset command — write True from HMI to reset faults"),

    # Diagnostics
    ("workpiecesCount",           "Completed Workpieces Count",      ua.VariantType.Int16,   False, "Total Number of Workpieces completed."),
    ("siemensPeerCommunicationOk",  "Siemens PeerComm OK",           ua.VariantType.Boolean, False, "Level 1 Modbus TCP peer link healthy."),
    ("controllerActive",              "Siemens Active",                 ua.VariantType.Boolean, False, "Seimens in-control Indicator."),
]

# --------------------------------------------------------------------------
# CHANGE [SRV-1]: TransferUnit output coils made writable (was False).
# rotateToConveyor / rotateToTable / vacuumGripper are physical actuators and
# must be drivable from SCADA. controllerActiveIndicator (heartbeat) stays
# read-only. Sensors (discrete inputs) and handshake registers stay read-only.
# --------------------------------------------------------------------------
TRANSFER_UNIT_NODES = [
    # Output coils
    ("rotateToConveyor",            "Rotate To Conveyor",             ua.VariantType.Boolean, True,  "Q1 — transfer unit motor toward conveyor belt"),
    ("rotateToTable",               "Rotate To Table",                ua.VariantType.Boolean, True,  "Q2 — transfer unit motor toward turntable"),
    ("vacuumGripper",               "Vacuum Gripper",                 ua.VariantType.Boolean, True,  "Q8 — vacuum valve active (gripping workpiece)"),
    ("controllerActiveIndicator",   "Controller Active Indicator",    ua.VariantType.Boolean, False, "Micro820 heartbeat indicator"),
    # Discrete inputs
    ("transferUnitAtConveyor",      "Transfer Unit At Conveyor",      ua.VariantType.Boolean, False, "S1 — limit switch at conveyor belt end"),
    ("transferUnitAtTurntable",     "Transfer Unit At Turntable",     ua.VariantType.Boolean, False, "S2 — limit switch at turntable end"),
    ("turntableInPosition",         "Turntable In Position (AB)",     ua.VariantType.Boolean, False, "S4 — turntable home position (AB-side read)"),
    
    # Holding registers
    ("siemensHandshakeCode",        "Siemens Handshake Code",         ua.VariantType.Int16,   False, "Handshake register read from Siemens"),
    ("schneiderHandShakeCode",        "Schneider Handshake Code",           ua.VariantType.Int16,   False, "Handshake register read from Schneider"),
    ("schneiderHandshakeACK",        "Schneider Handshake ACK",           ua.VariantType.Int16,   False, "Handshake register written by Schneider"),
    
    ("transferUnitPositionCode",    "Unit Position Code",             ua.VariantType.Int16,   False, "0=Unknown 1=AtTable 2=AtBelt 3=InTransit"),
]


# --------------------------------------------------------------------------
# CHANGE [SRV-1]: Conveyor output coils made writable (was False).
# conveyorBelt / separatorValve / sliderMotor are physical actuators.
# tm221ActiveIndicator (heartbeat) and all light-barrier/limit sensors stay
# read-only.
# --------------------------------------------------------------------------
CONVEYOR_NODES = [
    # Output coils
    ("conveyorBelt",                "Conveyor Belt Motor",            ua.VariantType.Boolean, True,  "Q5 — belt drive motor active"),
    ("separatorValve",              "Separator Valve",                ua.VariantType.Boolean, True,  "Q6 — separator valve active"),
    ("sliderMotor",                 "Slider Motor",                   ua.VariantType.Boolean, True,  "Q3 — motorised pusher active"),
    ("tm221ActiveIndicator",        "TM221 Active Indicator",         ua.VariantType.Boolean, False, "TM221 heartbeat indicator"),
    # Discrete inputs
    ("workpieceOnConveyor",         "Workpiece On Conveyor",          ua.VariantType.Boolean, False, "B1 — light barrier; workpiece on belt"),
    ("palletReady",                 "Pallet Ready",                   ua.VariantType.Boolean, False, "B2 — light barrier; pallet present"),
    ("workpieceOnPallet",           "Workpiece On Pallet",            ua.VariantType.Boolean, False, "B3 — light barrier; workpieces on pallet"),
    ("sliderInPosition",            "Slider In Position",             ua.VariantType.Boolean, False, "S3 — pusher slider at home position"),
]


#The following is meant to exploit the Ignition SCADA
#NOTE [SRV-2]: only added to the address space when ENABLE_EXPLOIT_NODES is True.
IGNITION_CLIENT_EXPLOITS = [
("explot", "Cross-Site-Scripting", ua.VariantType.String, False, "<script> alert(\"If you see this, The client is vulnerable from XSS!\"</script>")
]

# Source map — links each node tag to its client state dict 
# Built at runtime after imports resolve.

def _build_source_map() -> dict:
    src = {}
    for tag, *_ in TURNTABLE_NODES:
        src[tag] = (siemens_client.state, tag)
    for tag, *_ in TRANSFER_UNIT_NODES:
        src[tag] = (ab_cip_client.state, tag)
    for tag, *_ in CONVEYOR_NODES:
        src[tag] = (tm221_client.state, tag)
    # System nodes
    src["siemens_connected"] = (siemens_client.state, "_connected")
    src["ab_connected"]      = (ab_cip_client.state,  "_connected")
    src["tm221_connected"]   = (tm221_client.state,   "_connected")
    return src


def logged_connection_made(self, transport):
    peer = transport.get_extra_info("peername")
    log.info(f"Client connected: {peer}")
    return orig_connection_made(self, transport)

OPCUAProtocol.connection_made = logged_connection_made
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

    # CHANGE [SRV-2]: exploit zone only when explicitly enabled.
    if ENABLE_EXPLOIT_NODES:
        log.warning("ENABLE_EXPLOIT_NODES is True — adding hostile XSS test node")
        await _add_zone(matrix_node, "OPCUAClientExploits", IGNITION_CLIENT_EXPLOITS)

    await _build_benchmark_nodes(matrix_node, ns)

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

# --------------------------------------------------------------------------
# CHANGE [SRV-4]: generalised SCADA → PLC write-forwarding.
#
# OLD mechanism (removed): a hard-coded COMMAND_TAGS = {start, stop} set, with
# _last_command_seen/_last_command_time, forwarding only to siemens_client.
# It could not drive any TransferUnit/Conveyor actuator, skipped the reset
# command, and — critically — fought level actuators (see the race note below).
#
# NEW mechanism: one map tag → (client write coroutine, identifier). Every
# client exposes the same call shape  write(identifier, value):
#   siemens_client.write_node(tag, value)
#   ab_cip_client.write_tag(internal_tag, value)
#   tm221_client.write_tag(internal_tag, value)
# The map is built in run() (live mode only; the standalone mocks have no write
# functions).
# --------------------------------------------------------------------------
DEBOUNCE_SEC = 0.3
_WRITE_FORWARD_MAP: dict = {}     # tag -> (async write fn, identifier passed to it)
_last_pushed:        dict = {}    # tag -> last value the UPDATE LOOP wrote to the node
_last_forward_time:  dict = {}    # tag -> monotonic time of last forward (debounce)


def _build_write_forward_map() -> dict:
    """Build the tag → (write-coroutine, identifier) routing table (live mode)."""
    return {
        # Siemens — siemens_client.write_node(tag, value)
        "motorTurntable":      (siemens_client.write_node, "motorTurntable"),
        "drillActive":         (siemens_client.write_node, "drillActive"),
        "weldActive":          (siemens_client.write_node, "weldActive"),
        "sliderMagazine":      (siemens_client.write_node, "sliderMagazine"),
        "siemensStartCommand": (siemens_client.write_node, "siemensStartCommand"),
        # "siemensStopCommand":  (siemens_client.write_node, "siemensStopCommand"),
        # "siemensResetCommand": (siemens_client.write_node, "siemensResetCommand"),
        # Allen-Bradley — ab_cip_client.write_tag(internal_tag, value)
        "rotateToConveyor":    (ab_cip_client.write_tag, "rotateToConveyor"),
        "rotateToTable":       (ab_cip_client.write_tag, "rotateToTable"),
        "vacuumGripper":       (ab_cip_client.write_tag, "vacuumGripper"),
        # Schneider TM221 — tm221_client.write_tag(internal_tag, value)
        "conveyorBelt":        (tm221_client.write_tag, "conveyorBelt"),
        "separatorValve":      (tm221_client.write_tag, "separatorValve"),
        "sliderMotor":         (tm221_client.write_tag, "sliderMotor"),
    }


# ============================================================
# E2E BENCHMARK INTERFACE
# ============================================================

BENCHMARK_NODES = {
    "siemens_request": None,
    "siemens_response": None,

    "ab_request": None,
    "ab_response": None,

    "tm221_request": None,
    "tm221_response": None,

    # CHANGE [SRV-5]: write-path benchmark nodes
    "siemens_write_request": None,
    "siemens_write_response": None,

    "ab_write_request": None,
    "ab_write_response": None,

    "tm221_write_request": None,
    "tm221_write_response": None,
}

BENCHMARK_STATE = {
    "siemens_last_request": 0,
    "ab_last_request": 0,
    "tm221_last_request": 0,

    # CHANGE [SRV-5]: write-path last-request trackers
    "siemens_write_last_request": 0,
    "ab_write_last_request": 0,
    "tm221_write_last_request": 0,
}

async def _handle_command_writes(nodes: dict):
    """
    Forward fresh SCADA writes on writable nodes down to the owning PLC.

    Runs at the TOP of each update cycle, BEFORE the state-push for-loop, so a
    just-arrived HMI value is forwarded before it is overwritten by ground truth.

    CLOBBER-RACE FIX [SRV-4]: the update loop rewrites every node from PLC
    ground truth each cycle. The old code compared the node to a free-running
    "last seen" value, so one cycle after a SCADA write it would see the node
    reverted to ground truth and forward the STALE value back — fighting any
    level actuator (e.g. SCADA sets drillActive=True; next cycle the node reads
    back False from ground truth and the server re-forwards False, turning it
    off). Here we instead compare the node to `_last_pushed[tag]` — exactly what
    the update loop last wrote. A difference therefore means a genuine SCADA
    write, never our own echo, so we forward once and do not fight ground truth
    afterwards. The node may briefly show ground truth until the PLC reacts;
    that is the intended "reflect real state" behaviour.
    """
    for tag, (write_fn, ident) in _WRITE_FORWARD_MAP.items():
        node = nodes.get(tag)
        if node is None:
            continue
        try:
            current = await node.read_value()
        except Exception as exc:
            log.warning(f"Read writable node failed [{tag}]: {exc}")
            continue

        # First sight this run: adopt as baseline, do not forward.
        if tag not in _last_pushed:
            _last_pushed[tag] = current
            continue

        if current != _last_pushed[tag]:
            now_t = asyncio.get_event_loop().time()
            if now_t - _last_forward_time.get(tag, 0.0) < DEBOUNCE_SEC:
                continue
            _last_forward_time[tag] = now_t
            log.warning(f"  SCADA write {tag:<22} = {current}  → forwarding to PLC")
            try:
                await write_fn(ident, current)
            except Exception as exc:
                log.error(f"Forward to PLC failed [{tag}]: {exc}")
            # Adopt commanded value as baseline so we do not re-forward it next
            # cycle before ground truth catches up.
            _last_pushed[tag] = current


async def _build_benchmark_nodes(matrix_node, ns: int):
    """
    Creates a completely separate OPC-UA benchmark interface.

    These nodes are NOT part of the normal MATRIX process image.
    They are used only by the latency benchmark script.

    READ-path nodes (original): <PLC>_Request / <PLC>_Response — a fresh PLC
    READ is performed, then the request counter is echoed to the response node.

    WRITE-path nodes [SRV-5]: <PLC>_WriteRequest / <PLC>_WriteResponse — a fresh
    PLC WRITE to that client's benign scratch tag is performed, then echoed.
    """

    benchmark = await matrix_node.add_object(ns,"Benchmark")

    # ---- READ-path nodes (unchanged) ----
    # Siemens
    siemens_request = await benchmark.add_variable(ns,"Siemens_Request",0,ua.VariantType.Int64)

    siemens_response = await benchmark.add_variable(
        ns,
        "Siemens_Response",
        0,
        ua.VariantType.Int64
    )

    # Allen-Bradley
    ab_request = await benchmark.add_variable(
        ns,
        "AB_Request",
        0,
        ua.VariantType.Int64
    )

    ab_response = await benchmark.add_variable(
        ns,
        "AB_Response",
        0,
        ua.VariantType.Int64
    )

    # Schneider TM221
    tm221_request = await benchmark.add_variable(
        ns,
        "TM221_Request",
        0,
        ua.VariantType.Int64
    )

    tm221_response = await benchmark.add_variable(
        ns,
        "TM221_Response",
        0,
        ua.VariantType.Int64
    )

    # Allow benchmark PC to write request counters.
    await siemens_request.set_writable()
    await ab_request.set_writable()
    await tm221_request.set_writable()

    BENCHMARK_NODES["siemens_request"] = siemens_request
    BENCHMARK_NODES["siemens_response"] = siemens_response

    BENCHMARK_NODES["ab_request"] = ab_request
    BENCHMARK_NODES["ab_response"] = ab_response

    BENCHMARK_NODES["tm221_request"] = tm221_request
    BENCHMARK_NODES["tm221_response"] = tm221_response

    # ---- CHANGE [SRV-5]: WRITE-path nodes ----
    siemens_write_request  = await benchmark.add_variable(ns, "Siemens_WriteRequest",  0, ua.VariantType.Int64)
    siemens_write_response = await benchmark.add_variable(ns, "Siemens_WriteResponse", 0, ua.VariantType.Int64)
    ab_write_request       = await benchmark.add_variable(ns, "AB_WriteRequest",       0, ua.VariantType.Int64)
    ab_write_response      = await benchmark.add_variable(ns, "AB_WriteResponse",      0, ua.VariantType.Int64)
    tm221_write_request    = await benchmark.add_variable(ns, "TM221_WriteRequest",    0, ua.VariantType.Int64)
    tm221_write_response   = await benchmark.add_variable(ns, "TM221_WriteResponse",   0, ua.VariantType.Int64)

    await siemens_write_request.set_writable()
    await ab_write_request.set_writable()
    await tm221_write_request.set_writable()

    BENCHMARK_NODES["siemens_write_request"]  = siemens_write_request
    BENCHMARK_NODES["siemens_write_response"] = siemens_write_response
    BENCHMARK_NODES["ab_write_request"]       = ab_write_request
    BENCHMARK_NODES["ab_write_response"]      = ab_write_response
    BENCHMARK_NODES["tm221_write_request"]    = tm221_write_request
    BENCHMARK_NODES["tm221_write_response"]   = tm221_write_response

    log.info("Benchmark OPC-UA interface created (read-path + write-path).")

    return benchmark


async def _benchmark_loop():
    """
    Processes benchmark requests independently of the normal
    MATRIX state/update loop.

    Request:
        SCADA benchmark PC -> Middleware
    Processing:
        Middleware -> PLC -> Middleware
    Response:
        Middleware -> SCADA benchmark PC
    """

    while True:

        # ====================================================
        # READ-path — Siemens
        # ====================================================
        try:
            node = BENCHMARK_NODES["siemens_request"]
            request = await node.read_value()
            if request != BENCHMARK_STATE["siemens_last_request"]:
                BENCHMARK_STATE["siemens_last_request"] = request
                # Fresh PLC read
                await siemens_client.benchmark_read("motorTurntable")
                # Acknowledge request
                await BENCHMARK_NODES["siemens_response"].write_value(request)
        except Exception as exc:
            log.warning(f"Siemens benchmark request failed: {exc}")

        # ====================================================
        # READ-path — Allen-Bradley
        # ====================================================
        try:
            node = BENCHMARK_NODES["ab_request"]
            request = await node.read_value()
            if request != BENCHMARK_STATE["ab_last_request"]:
                BENCHMARK_STATE["ab_last_request"] = request
                # Fresh PLC CIP tag read
                await ab_cip_client.benchmark_read("SchneiderModbusHandshake")
                # Acknowledge
                await BENCHMARK_NODES["ab_response"].write_value(request)
        except Exception as exc:
            log.warning(f"AB benchmark request failed: {exc}")

        # ====================================================
        # READ-path — Schneider TM221
        # ====================================================
        try:
            node = BENCHMARK_NODES["tm221_request"]
            request = await node.read_value()
            if request != BENCHMARK_STATE["tm221_last_request"]:
                BENCHMARK_STATE["tm221_last_request"] = request
                # Fresh PLC coil read
                await tm221_client.benchmark_read_coil(address=0)
                # Acknowledge
                await BENCHMARK_NODES["tm221_response"].write_value(request)
        except Exception as exc:
            log.warning(f"TM221 benchmark request failed: {exc}")

        # ====================================================
        # CHANGE [SRV-5]: WRITE-path benchmarks (scratch-tag writes).
        # Guarded so the standalone mocks (no benchmark_write) don't spam.
        # Each response is echoed ONLY if the scratch write actually ran
        # (benchmark_write returns False when its scratch tag is unconfigured),
        # so an unconfigured scratch tag shows up as a benchmark timeout rather
        # than a falsely-fast number.
        # ====================================================
        if not _STANDALONE:
            # WRITE-path — Siemens
            try:
                node = BENCHMARK_NODES["siemens_write_request"]
                request = await node.read_value()
                if request != BENCHMARK_STATE["siemens_write_last_request"]:
                    BENCHMARK_STATE["siemens_write_last_request"] = request
                    if await siemens_client.benchmark_write(request):
                        await BENCHMARK_NODES["siemens_write_response"].write_value(request)
            except Exception as exc:
                log.warning(f"Siemens write-benchmark failed: {exc}")

            # WRITE-path — Allen-Bradley
            try:
                node = BENCHMARK_NODES["ab_write_request"]
                request = await node.read_value()
                if request != BENCHMARK_STATE["ab_write_last_request"]:
                    BENCHMARK_STATE["ab_write_last_request"] = request
                    if await ab_cip_client.benchmark_write(request):
                        await BENCHMARK_NODES["ab_write_response"].write_value(request)
            except Exception as exc:
                log.warning(f"AB write-benchmark failed: {exc}")

            # WRITE-path — Schneider TM221
            try:
                node = BENCHMARK_NODES["tm221_write_request"]
                request = await node.read_value()
                if request != BENCHMARK_STATE["tm221_write_last_request"]:
                    BENCHMARK_STATE["tm221_write_last_request"] = request
                    if await tm221_client.benchmark_write(request):
                        await BENCHMARK_NODES["tm221_write_response"].write_value(request)
            except Exception as exc:
                log.warning(f"TM221 write-benchmark failed: {exc}")

        # Small polling interval.
        # This is ONLY the benchmark request detector.
        await asyncio.sleep(0.001)

async def _update_loop(nodes: dict, start_time: datetime):
    source_map = _build_source_map()
    log.info(f"Update loop running — {UPDATE_INTERVAL}s interval")

    while True:
        try:
            now    = datetime.now(timezone.utc)
            uptime = str(now - start_time).split(".")[0]

            await nodes["middleware_uptime"].write_value(uptime)
            await nodes["last_update"].write_value(now.isoformat())
            await _handle_command_writes(nodes)
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
                    # CHANGE [SRV-4]: remember what the update loop pushed, so
                    # _handle_command_writes can tell a real SCADA write apart
                    # from our own ground-truth echo. All forwardable tags are
                    # Boolean, so bool(raw) is the comparable pushed value.
                    if tag in _WRITE_FORWARD_MAP:
                        _last_pushed[tag] = bool(raw)
                except Exception as exc:
                    log.warning(f"Node write failed [{tag}]: {exc}")

        except Exception as exc:
            log.error(f"Update loop error: {exc}")

        await asyncio.sleep(UPDATE_INTERVAL)

# Main 

# --------------------------------------------------------------------------
# CHANGE [SRV-3]: apply the configured server security. Default "none" issues
# the exact same single call the server used before.
# --------------------------------------------------------------------------

async def _apply_server_security(server: Server):
    if SERVER_SECURITY_MODE == "none":
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        log.info("Server security: NoSecurity (unauthenticated) — default")
        return

    if SERVER_SECURITY_MODE == "userpass":
        from asyncua.server.users import User, UserRole
        server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])

        class _UserManager:
            def get_user(self, iserver, username=None, password=None, certificate=None):
                if username in SERVER_USERS and SERVER_USERS[username] == password:
                    return User(role=UserRole.User)
                return None

        server.user_manager = _UserManager()
        log.info("Server security: username/password (Basic256Sha256)")
        return

    if SERVER_SECURITY_MODE == "cert":
        server.set_security_policy([
            ua.SecurityPolicyType.Basic256Sha256_Sign,
            ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
        ])
        if SERVER_CERT:
            await server.load_certificate(SERVER_CERT)
        if SERVER_PRIVATE_KEY:
            await server.load_private_key(SERVER_PRIVATE_KEY)
        log.info("Server security: certificate (Basic256Sha256)")
        return

    # Unknown mode → fail safe to NoSecurity but shout about it.
    log.error(f"Unknown SERVER_SECURITY_MODE '{SERVER_SECURITY_MODE}' — falling back to NoSecurity")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])


async def run():
    server = Server()
    await server.init()
    server.set_endpoint(SERVER_ENDPOINT)
    server.set_server_name(SERVER_NAME)

    # CHANGE [SRV-3]: was `server.set_security_policy([NoSecurity])`; now routed
    # through _apply_server_security so auth can be enabled via config. Default
    # is identical (NoSecurity).
    await _apply_server_security(server)

    ns = await server.register_namespace(NAMESPACE_URI)
    log.info(f"Namespace '{NAMESPACE_URI}' → index {ns}")

    nodes      = await _build_address_space(server, ns)
    start_time = datetime.now(timezone.utc)

    # CHANGE [SRV-4]: build the SCADA→PLC write-forward map (live mode only;
    # the standalone mocks have no write functions). _last_pushed is seeded
    # False so a False node at startup is not spuriously forwarded.
    global _WRITE_FORWARD_MAP
    if not _STANDALONE:
        _WRITE_FORWARD_MAP = _build_write_forward_map()
        for tag in _WRITE_FORWARD_MAP:
            _last_pushed.setdefault(tag, False)
        log.info(f"SCADA→PLC write-forwarding enabled for {len(_WRITE_FORWARD_MAP)} tags")

    # --------------------------------------------------------------------------
    # CHANGE [SRV-7] (2026-10-29): retry the OPC-UA server bind instead of dying
    # once.
    #
    # WHY: the server binds to the SCADA-side static IP 192.168.100.10. At boot
    # (systemd), and intermittently after a network blip, that address can be
    # assigned to eth0 a moment AFTER this process starts. `async with server:`
    # calls server.start() → create_server(), which then throws
    # OSError "could not bind on any address out of [('192.168.100.10', 4840)]".
    # Previously that killed the server task for good, while main.py's
    # gather(return_exceptions=True) kept the PLC clients looping — so the whole
    # middleware looked "up" but was unreachable (the intermittent failure seen
    # in the logs).
    #
    # FIX: wrap the bind in the same self-healing retry the PLC clients already
    # use. On OSError we wait BIND_RETRY_DELAY and try again until the address
    # exists. Everything above (init, security, namespace, address space, the
    # write-forward map) does not touch the socket and is built once, before the
    # loop; only the bind + serve is retried.
    #
    # NOTE: if 192.168.100.10 never comes up (genuine misconfig, not a race),
    # this retries forever by design. If `ss -ltnp | grep 4840` shows nothing
    # for more than ~30 s after boot, check `ip addr` — the IP is missing, not
    # racing.
    # --------------------------------------------------------------------------
    BIND_RETRY_DELAY = 5  # seconds between bind attempts

    while True:
        try:
            async with server:
                log.info(f"OPC-UA server listening at {SERVER_ENDPOINT}")
                log.info("Connect Ignition OPC-UA driver to this endpoint.")
                # run() runs BOTH the state/update loop and the benchmark loop
                # for the lifetime of the server. (CHANGE [SRV-6]: removed the
                # confusing #TO-DO toggle markers and the dead commented
                # single-loop line; behaviour is the same as before.)
                update_task    = asyncio.create_task(_update_loop(nodes, start_time))
                benchmark_task = asyncio.create_task(_benchmark_loop())
                try:
                    await asyncio.gather(update_task, benchmark_task)
                finally:
                    update_task.cancel()
                    benchmark_task.cancel()
            # Clean exit of the server context (not a bind failure) → stop.
            break
        except OSError as exc:
            # Almost always: 192.168.100.10 not on an interface yet (boot race).
            log.error(f"Server bind failed ({exc}); retrying in {BIND_RETRY_DELAY}s ...")
            await asyncio.sleep(BIND_RETRY_DELAY)


if __name__ == "__main__":
    print(f"opcua_server.py — {'STANDALONE (mock)' if _STANDALONE else 'LIVE'}")
    print(f"Endpoint: {SERVER_ENDPOINT}")
    print("Browse with UaExpert: opc.tcp://localhost:4840\n")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")