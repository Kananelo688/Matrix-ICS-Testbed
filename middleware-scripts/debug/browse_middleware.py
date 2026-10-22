"""
    browse_middleware_nodes.py

    Connects to the middleware's OPC-UA server (opcua_server.py) and prints
    every exposed variable's full path, NodeId, and whether it's writable
    (via the OPC-UA AccessLevel attribute — bit 0x02 = CurrentWrite).

    Use this to get real, current NodeIds for middleware_latency.py instead
    of guessing them — the namespace index can shift between server restarts.
"""

from asyncua.sync import Client
from asyncua import ua

URL = "opc.tcp://192.168.100.10:4840"


def browse_recursive(node, path=""):
    results = []
    for child in node.get_children():
        try:
            bname = child.read_browse_name().Name
        except Exception:
            continue

        current_path = f"{path}/{bname}"

        try:
            node_class = child.read_node_class()
        except Exception:
            continue

        if node_class == ua.NodeClass.Variable:
            try:
                access_level = child.read_attribute(ua.AttributeIds.AccessLevel).Value.Value #type: ignore
                writable = bool(access_level & 0x02)  # CurrentWrite bit
            except Exception:
                writable = None
            results.append((current_path, child.nodeid.to_string(), writable))
        else:
            # Object / folder — recurse into it
            results.extend(browse_recursive(child, current_path))

    return results


if __name__ == "__main__":
    print(f"Connecting to {URL} ...")
    with Client(url=URL) as client:
        objects = client.get_objects_node()
        all_vars = browse_recursive(objects, "Objects")

    print(f"\nFound {len(all_vars)} variables:\n")
    print(f"{'NodeId':<22} {'Writable':<10} Path")
    print("-" * 70)
    for path, node_id, writable in all_vars:
        print(f"{node_id:<22} {str(writable):<10} {path}")