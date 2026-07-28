import asyncio
from asyncua import Client

PLC_URL = "opc.tcp://192.168.50.10:4840"

async def dump_all_tags():
    async with Client(url=PLC_URL) as client:
        # Get the ServerInterface node under ServerInterfaces
        print("\n--- Discovering All Tags inside ServerInterface ---")
        
        # Struct nodes from your log
        struct_ids = {
            "Turntable": "ns=4;i=4",
            "Commands": "ns=4;i=17",
            "Diagnostics": "ns=4;i=23"
        }
        
        for struct_name, node_id in struct_ids.items():
            print(f"\n[{struct_name}] ({node_id}):")
            try:
                struct_node = client.get_node(node_id)
                children = await struct_node.get_children()
                for child in children:
                    disp = await child.read_display_name()
                    print(f"  ├── {disp.Text:<30} -> NodeId: {child.nodeid.to_string()}")
            except Exception as e:
                print(f"  Error reading {struct_name}: {e}")

if __name__ == "__main__":
    asyncio.run(dump_all_tags())