#!/usr/bin/env python3
"""
scada_write_tester.py

MATRIX Testbed — interactive SCADA-side OPC-UA write tester.


    A standalone OPC-UA *client* that behaves like Ignition/UaExpert OPC Clients would. It
    connects to the Raspberry Pi middleware aggregation server and writes to the
    writable actuator / command nodes. You type an internal tag name (e.g.
    "drillActive") and a value, and it writes it. It then reads the node back —
    immediately and again after a short delay — so you can SEE whether the write
    stuck or was reverted by PLC ground truth.

    To exercise, by hand, the whole SCADA → middleware → PLC write path:
        this client  ──OPC-UA write──▶  middleware node
        middleware   ──_handle_command_writes──▶  siemens/ab/tm221 client
        PLC client   ──OPC-UA / CIP / Modbus──▶  the actuator tag
    If a write reaches the node but not the actuator, that is a PLC-program
    ownership issue (the PLC logic re-asserts the output every scan), not a
    middleware issue — this tool helps you tell the two apart.

    You type the INTERNAL tag name ("drillActive"). On the OPC-UA server these
    nodes have human display names ("Drill Active") inside folders
    (Objects/MATRIX/<Zone>/<Display>). The WRITABLE map below holds the
    internal→(zone, display) mapping — it mirrors exactly the writable=True
    nodes in opcua_server.py — so you never have to remember display names.

USAGE
    python scada_write_tester.py
    python scada_write_tester.py opc.tcp://192.168.100.10:4840     # override URL
    python scada_write_tester.py opc.tcp://localhost:4840          # on the Pi itself

    Then at the prompt:
        list                     show all writable tags
        drillActive true         write True  to drillActive
        drillActive 0            write False to drillActive
        drillActive              (no value) → writes True, with a note
        read drillActive         read the node's current value
        toggle conveyorBelt      flip the current value
        pulse siemensStartCommand 300   write True, wait 300 ms, write False
        watch drillActive 5      sample the node for 5 seconds, print changes
        help                     show commands
        quit / exit              disconnect and leave

SAFETY
    Writing these tags drives REAL actuators (motors, valves, the drill). Keep
    the physical e-stop in reach. Prefer testing one stage at a time.

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import asyncio
import logging
import sys
from asyncua import Client, ua

# ==========================================================================
# CONFIGURATION
# ==========================================================================

# SCADA-side endpoint of the Pi middleware OPC-UA server. Override on the
# command line (argv[1]) — e.g. use localhost when running on the Pi itself.
SERVER_URL    = "opc.tcp://192.168.100.10:4840"

# Must match NAMESPACE_URI in opcua_server.py. Used to resolve the namespace
# index at runtime (so we never hard-code ns=2, which can change).
NAMESPACE_URI = "urn:MATRIX.Middleware.OPC-UA"

# Optional authentication (default OFF — matches the server's default build).
# Set these only once you enable auth on the server (SERVER_SECURITY_MODE).
#   SECURITY_STRING e.g. "Basic256Sha256,SignAndEncrypt,client_cert.der,client_key.pem"
USERNAME        = None
PASSWORD        = None
SECURITY_STRING = None

# How long (seconds) after a write to take the second read-back. Must be a bit
# longer than the server UPDATE_INTERVAL (0.5 s) and the Siemens publish
# interval (~1 s) so you actually see ground truth catch up.
READBACK_DELAY  = 1.2

CONNECT_RETRIES = 5      # startup connection attempts
RECONNECT_DELAY = 3      # seconds between attempts

# ==========================================================================
# WRITABLE TAG MAP — MIRRORS opcua_server.py (every writable=True node).
# internal tag name : (zone folder, node display name)
# If you change a display name or add a writable node in the server, mirror it
# here or this tester won't find it.
# ==========================================================================
WRITABLE = {
    # --- Turntable (Siemens S7-1200, via OPC-UA) ---
    "motorTurntable":      ("Turntable",    "Motor Turntable"),
    "drillActive":         ("Turntable",    "Drill Active"),
    "weldActive":          ("Turntable",    "Weld Active"),
    "sliderMagazine":      ("Turntable",    "Slider Magazine"),
    "siemensStartCommand": ("Turntable",    "Siemens Start Command"),
    "siemensStopCommand":  ("Turntable",    "Siemens Stop Command"),
    "siemensResetCommand": ("Turntable",    "Siemens Reset Command"),
    # --- Transfer Unit (Allen-Bradley Micro820, via EtherNet/IP) ---
    "rotateToConveyor":    ("TransferUnit", "Rotate To Conveyor"),
    "rotateToTable":       ("TransferUnit", "Rotate To Table"),
    "vacuumGripper":       ("TransferUnit", "Vacuum Gripper"),
    # --- Conveyor (Schneider TM221, via Modbus TCP) ---
    "conveyorBelt":        ("Conveyor",     "Conveyor Belt Motor"),
    "separatorValve":      ("Conveyor",     "Separator Valve"),
    "sliderMotor":         ("Conveyor",     "Slider Motor"),
}

# ==========================================================================
# LOGGING
# ==========================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Keep asyncua's own chatter quiet so the REPL stays readable.
logging.getLogger("asyncua").setLevel(logging.ERROR)
log = logging.getLogger("WRITE_TESTER")


# ==========================================================================
# VALUE PARSING / COERCION
# ==========================================================================

_TRUE_WORDS  = {"1", "true", "t", "on", "yes", "y", "high", "set"}
_FALSE_WORDS = {"0", "false", "f", "off", "no", "n", "low", "clear"}


def parse_bool(text: str):
    """Parse a human boolean. Returns True/False, or None if unrecognised."""
    t = text.strip().lower()
    if t in _TRUE_WORDS:
        return True
    if t in _FALSE_WORDS:
        return False
    return None


def coerce_to_variant_type(text: str, vtype: ua.VariantType):
    """
    Convert the user's typed value into the Python type the node expects.
    All 13 writable MATRIX nodes are Boolean today; integer handling is here so
    the tool keeps working if you later make an Int tag writable.
    Returns (value, error_message_or_None).
    """
    if vtype == ua.VariantType.Boolean:
        b = parse_bool(text)
        if b is None:
            return None, f"'{text}' is not a boolean (try: true/false, 1/0, on/off)"
        return b, None

    if vtype in (ua.VariantType.Int16, ua.VariantType.Int32,
                 ua.VariantType.Int64, ua.VariantType.UInt16,
                 ua.VariantType.UInt32, ua.VariantType.UInt64, ua.VariantType.Byte):
        try:
            return int(text), None
        except ValueError:
            return None, f"'{text}' is not an integer"

    # Fallback: pass through as string.
    return text, None


# ==========================================================================
# CONNECTION
# ==========================================================================

async def _apply_security(client: Client):
    """Apply auth if configured. No-op by default (unauthenticated)."""
    if USERNAME is not None:
        client.set_user(USERNAME)
    if PASSWORD is not None:
        client.set_password(PASSWORD)
    if SECURITY_STRING is not None:
        await client.set_security_string(SECURITY_STRING)
        log.info(f"Client security applied: {SECURITY_STRING.split(',')[0]}")


async def connect(url: str) -> Client:
    """
    Connect to the server with a few retries (the server may still be settling
    after a reboot). Returns a connected Client, or raises after the last try.
    """
    last_exc = None
    for attempt in range(1, CONNECT_RETRIES + 1):
        client = Client(url=url)
        await _apply_security(client)
        try:
            await client.connect()
            log.info(f"Connected to {url}")
            return client
        except Exception as exc:
            last_exc = exc
            log.warning(f"Connect attempt {attempt}/{CONNECT_RETRIES} failed: {exc}")
            try:
                await client.disconnect()
            except Exception:
                pass
            if attempt < CONNECT_RETRIES:
                await asyncio.sleep(RECONNECT_DELAY)
    raise ConnectionError(f"Could not connect to {url}: {last_exc}")


async def resolve_nodes(client: Client) -> dict:
    """
    Resolve every writable tag to its live Node object by walking the browse
    path  Objects/MATRIX/<Zone>/<Display>.  Returns {internal_tag: Node}.
    Any tag that fails to resolve is reported and skipped (so a single naming
    mismatch doesn't kill the whole tool).
    """
    ns = await client.get_namespace_index(NAMESPACE_URI)
    log.info(f"Namespace '{NAMESPACE_URI}' → index {ns}")

    objects = client.nodes.objects
    resolved = {}
    for tag, (zone, display) in WRITABLE.items():
        path = [f"{ns}:MATRIX", f"{ns}:{zone}", f"{ns}:{display}"]
        try:
            node = await objects.get_child(path)
            resolved[tag] = node
        except Exception as exc:
            log.error(f"Could not resolve '{tag}'  (path {'/'.join(path)}): {exc}")

    log.info(f"Resolved {len(resolved)}/{len(WRITABLE)} writable tags")
    return resolved


# ==========================================================================
# CORE OPERATIONS
# ==========================================================================

async def read_tag(node) -> object:
    """Read a node's current value."""
    return await node.read_value()


async def write_tag(node, value) -> None:
    """
    Write `value` to `node`, typed to the node's own data type so the server
    never rejects it with BadTypeMismatch. Raises on failure.
    """
    vtype = await node.read_data_type_as_variant_type()
    coerced = value
    if not isinstance(value, (bool, int, str)):
        coerced = value
    dv = ua.DataValue(ua.Variant(coerced, vtype))
    await node.write_value(dv)


async def do_write(nodes: dict, tag: str, raw_value: str):
    """
    Full write cycle with before/after read-back so you can see what happened:
      before  — value just before the write
      after   — value immediately after (should be your commanded value)
      settled — value after READBACK_DELAY (ground truth; may differ if the PLC
                program owns the output and re-asserted it)
    """
    node = nodes.get(tag)
    if node is None:
        print(f"  ✗ unknown or unresolved tag '{tag}'  (type 'list')")
        return

    vtype = await node.read_data_type_as_variant_type()
    value, err = coerce_to_variant_type(raw_value, vtype)
    if err:
        print(f"  ✗ {err}")
        return

    try:
        before = await read_tag(node)
        await write_tag(node, value)
        after = await read_tag(node)
        await asyncio.sleep(READBACK_DELAY)
        settled = await read_tag(node)
    except Exception as exc:
        print(f"  ✗ write failed: {exc}")
        return

    print(f"  → wrote {tag} = {value}")
    print(f"      before          : {before}")
    print(f"      immediately after: {after}")
    print(f"      after {READBACK_DELAY:>4}s      : {settled}")
    # Interpretation hint — the thing that confuses people most.
    if after == value and settled != value:
        print("      NOTE: value reverted — the PLC program likely owns this "
              "output and re-asserted it (expected for sensor-driven outputs).")
    elif after != value:
        print("      NOTE: the node did not even hold the value — check the tag "
              "is actually writable on the server.")


async def do_read(nodes: dict, tag: str):
    node = nodes.get(tag)
    if node is None:
        print(f"  ✗ unknown or unresolved tag '{tag}'  (type 'list')")
        return
    try:
        print(f"  {tag} = {await read_tag(node)}")
    except Exception as exc:
        print(f"  ✗ read failed: {exc}")


async def do_toggle(nodes: dict, tag: str):
    node = nodes.get(tag)
    if node is None:
        print(f"  ✗ unknown or unresolved tag '{tag}'  (type 'list')")
        return
    try:
        current = await read_tag(node)
    except Exception as exc:
        print(f"  ✗ read failed: {exc}")
        return
    await do_write(nodes, tag, "false" if current else "true")


async def do_pulse(nodes: dict, tag: str, ms_text: str):
    """Momentary write: True, wait, False. Good for start/stop/reset commands."""
    node = nodes.get(tag)
    if node is None:
        print(f"  ✗ unknown or unresolved tag '{tag}'  (type 'list')")
        return
    try:
        ms = int(ms_text)
    except ValueError:
        print(f"  ✗ pulse width '{ms_text}' is not an integer (milliseconds)")
        return
    try:
        await write_tag(node, True)
        print(f"  → {tag} = True  (holding {ms} ms)")
        await asyncio.sleep(ms / 1000.0)
        await write_tag(node, False)
        print(f"  → {tag} = False (pulse done)")
    except Exception as exc:
        print(f"  ✗ pulse failed: {exc}")


async def do_watch(nodes: dict, tag: str, secs_text: str):
    """Sample a node for N seconds and print every value change."""
    node = nodes.get(tag)
    if node is None:
        print(f"  ✗ unknown or unresolved tag '{tag}'  (type 'list')")
        return
    try:
        secs = float(secs_text)
    except ValueError:
        print(f"  ✗ watch duration '{secs_text}' is not a number (seconds)")
        return

    print(f"  watching {tag} for {secs:.0f}s (Ctrl+C in-loop not supported; it just ends)")
    last = object()
    loop = asyncio.get_event_loop()
    end = loop.time() + secs
    while loop.time() < end:
        try:
            val = await read_tag(node)
        except Exception as exc:
            print(f"  ✗ read failed: {exc}")
            return
        if val != last:
            print(f"      t={secs - (end - loop.time()):5.2f}s   {tag} = {val}")
            last = val
        await asyncio.sleep(0.1)
    print("  watch done")


def print_tags():
    print("\n  Writable tags (type the name on the left):")
    current_zone = None
    for tag, (zone, display) in WRITABLE.items():
        if zone != current_zone:
            print(f"\n    [{zone}]")
            current_zone = zone
        print(f"      {tag:<22} → \"{display}\"")
    print()


def print_help():
    print("""
  Commands:
    list                         list all writable tags
    <tag> <value>                write a value   (true/false, 1/0, on/off)
    <tag>                        write True (convenience; prints a note)
    read <tag>                   read current value
    toggle <tag>                 flip current value
    pulse <tag> [ms]             write True, wait ms (default 300), write False
    watch <tag> [seconds]        print value changes for N seconds (default 5)
    help                         this help
    quit / exit                  disconnect and leave
""")


# ==========================================================================
# REPL
# ==========================================================================

async def repl(nodes: dict):
    print_tags()
    print_help()
    while True:
        # Read stdin without blocking the asyncio event loop.
        try:
            line = await asyncio.to_thread(input, "write> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            return
        if cmd in ("help", "?"):
            print_help()
            continue
        if cmd in ("list", "ls"):
            print_tags()
            continue
        if cmd == "read" and len(parts) >= 2:
            await do_read(nodes, parts[1])
            continue
        if cmd == "toggle" and len(parts) >= 2:
            await do_toggle(nodes, parts[1])
            continue
        if cmd == "pulse" and len(parts) >= 2:
            await do_pulse(nodes, parts[1], parts[2] if len(parts) >= 3 else "300")
            continue
        if cmd == "watch" and len(parts) >= 2:
            await do_watch(nodes, parts[1], parts[2] if len(parts) >= 3 else "5")
            continue

        # Otherwise treat the first token as a tag name.
        tag = parts[0]
        if tag not in WRITABLE:
            print(f"  ✗ '{tag}' is not a writable tag (type 'list' or 'help')")
            continue
        if len(parts) == 1:
            print("  (no value given → writing True)")
            await do_write(nodes, tag, "true")
        else:
            await do_write(nodes, tag, parts[1])


# ==========================================================================
# MAIN
# ==========================================================================

async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else SERVER_URL

    print("=" * 70)
    print(" MATRIX SCADA write tester")
    print(f" target: {url}")
    print(" WARNING: writes drive REAL actuators — keep the e-stop in reach.")
    print("=" * 70)

    client = await connect(url)
    try:
        nodes = await resolve_nodes(client)
        if not nodes:
            print("No writable tags resolved — is this the right server / namespace?")
            return
        await repl(nodes)
    finally:
        try:
            await client.disconnect()
            log.info("Disconnected.")
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")