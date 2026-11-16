#!/usr/bin/env python3
"""
opcua_server.py

MATRIX Testbed - Network Traffic OPC-UA Server

OVERVIEW
    This subsystem monitors the network traffic at an interface
    (we recommend connecting it to a SPAN port), and publishes the
    network traffic information via an OPC-UA server.
    Each network channel (a predefined destination and source IP/MAC,
    and vice versa) is listed as its own OPC-UA variable node.
    The node stores a buffer of the network packets, which gets updated when:
    - a new batch of 100 packets is available to be published
    - a packet hasn't been published for over 2 seconds,
        triggering the entire channel to be published
    - the packet stream from `dumpcap` fails/terminates,
        so the remaining packets are published

    Packets are also saved to a classic `.pcap` file, in case using that for later analysis is easier.

CLI USAGE
    To run this subsystem, use:
        python opcua_server.py --id experiment_id

    The optional flags for the invocation are:
    - --description : free-text description for this run |
    - --iface : capture interface (device path or name from `dumpcap -D`) |
    - --results : directory to save result in |
    - -f : (no argument) forces saving data to the directory, without checking if data is being overwritten |

Author : MATRIX / Intelligent Connectivity Group - UCT
"""

# IMPORTS ================================

# External
import asyncio
import threading
import traceback
from dataclasses import asdict
from asyncua import Server, ua
from asyncua.common.structures104 import new_struct, new_struct_field
import time

# Internal
import network_monitor as nm
import packet_parser as pp

# CONSTANTS ================================

_ENDPOINT_URL = "opc.tcp://0.0.0.0:4840/matrix/" # TODO: Confirm with supervisor
_NAMESPACE_URI = "http://matrix.uct.ac.za/scada" # TODO: Confirm with supervisor
_BATCH_SIZE = 100 # size of buffer for OPC-UA nodes
_FLUSH_TIMEOUT = 2.0 # maximum time in seconds for a partially filled batch to wait, until it's flushed
_CHECK_INTERVAL = 0.5 # how often to check for timeouts when no packets arrive, in seconds

# OPC-UA struct fields: (OPC-UA name, `PacketInfo`` key, type, default for missing values)
_FIELDS = [
    ("Timestamp",   "timestamp",    ua.VariantType.Double,  0.0),
    ("Length",      "length",       ua.VariantType.UInt32,  0),
    ("SrcMac",      "src_mac",      ua.VariantType.String,  ""),
    ("DstMac",      "dst_mac",      ua.VariantType.String,  ""),
    ("SrcName",     "src_name",     ua.VariantType.String,  ""),
    ("DstName",     "dst_name",     ua.VariantType.String,  ""),
    ("SrcIp",       "src_ip",       ua.VariantType.String,  ""),
    ("DstIp",       "dst_ip",       ua.VariantType.String,  ""),
    ("Protocol",    "protocol",     ua.VariantType.String,  ""),
    ("SrcPort",     "src_port",     ua.VariantType.UInt16,  0),
    ("DstPort",     "dst_port",     ua.VariantType.UInt16,  0),
]

# HELPER FUNCTIONS ================================

def _capture_worker(loop:asyncio.AbstractEventLoop, queue:asyncio.Queue, handler):
    """
    The worker to capture packets, running on a separate thread.
    It puts network packets and their channel into a queue,
    to be read in the main thread
    Args:
        loop (asyncio.AbstractEventLoop): The main loop
        queue (asyncio.Queue): The queue to put packet-channel values in
        handler (subprocess.Popen): The `dumpcap` handler from which the packet stream comes
    """
    try:
        # Get packet stream reader
        no_file, reader = pp.open_packet_source(stream=handler.stream)

        # Put packets in the queue
        for packet, channel in pp.iter_packets(reader):
            loop.call_soon_threadsafe(queue.put_nowait, (packet, channel))
    except Exception:
        print("Capture worker failed:", flush=True)
        traceback.print_exc() # full traceback, printed from this thread
    finally:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, None) # "stream ended" notification
        except RuntimeError:
            pass # event loop already closed (normal during shutdown)

def _to_record(packet:pp.PacketInfo) -> "ua.PacketRecord":
    """
    Converts one parsed-packet `dict` into a `PacketRecord` struct instance
    Args:
        packet (PacketInfo): The packet information
    Returns:
        asyncua.ua.PacketRecord: The packet information formatted as a `PacketRecord`
    """
    # Convert data class to a dictionary
    packet_dict = asdict(packet)

    # Create the struct
    record = ua.PacketRecord()

    # Transfer each field/member
    for ua_name, key, variant_type, default in _FIELDS:
        value = packet_dict.get(key)
        if value is None:
            setattr(record, ua_name, default) # set to default value
        else:
            setattr(record, ua_name, value) # use the given value
    
    # Return
    return record

# API FUNCTIONS ================================

async def main():
    # Create the capture worker thread
    loop = asyncio.get_running_loop() # main loop
    queue = asyncio.Queue() # queue to transfer files
    dumpcap_handler = nm.trusted_start(True) # handler for packet stream
    threading.Thread(target=_capture_worker, args=(loop, queue, dumpcap_handler), daemon=True).start()

    # Start OPC-UA server
    server = Server()
    await server.init()
    server.set_endpoint(_ENDPOINT_URL)
    idx = await server.register_namespace(_NAMESPACE_URI)

    # Define struct type in the server
    struct_fields = []
    for ua_name, key, variant_type, default in _FIELDS:
        struct_fields.append(new_struct_field(ua_name, variant_type))
    struct_node, struct_encoding = await new_struct(server, idx, "PacketRecord", struct_fields) # create the new struct
    await server.load_data_type_definitions() # update definitions

    # Create channels (variable nodes)
    channels_obj = await server.nodes.objects.add_object(idx, "Channels")
    buffers = {} # channel name -> list of records (placeholder batching)
    variables = {} # channel name -> variable node
    first_seen = {} # channel name -> time when the oldest buffered packet arrived
    for channel in pp.get_channels():
        buffers[channel] = []
        variables[channel] = await channels_obj.add_variable(
            idx,
            channel,
            [], # initially an empty array
            varianttype=ua.VariantType.ExtensionObject,
            datatype=struct_node.nodeid,
        )

    async def flush(channel:str):
        """
        Publishes a channel's buffer (full or partial) as the node's new value,
        then empties the buffer
        Args:
            channel (str): The channel to flush
        """
        # Extract and empty the buffer
        batch = buffers[channel]
        buffers[channel] = []

        # Remove the first-seen value
        first_seen.pop(channel, None)

        # Publish
        if batch: # the batch has elements
            await variables[channel].write_value(ua.Variant(batch, ua.VariantType.ExtensionObject))

    try:
        async with server:
            while True:
                # Wait for the next packet, but wake up regularly to check for timeouts
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_CHECK_INTERVAL)
                except asyncio.TimeoutError:
                    item = False # no packet arrived before the timeout

                # Check if packet stream ended
                if item is None: # checks if packet stream ended, according to the capture-worker
                    print("Packet stream ended")
                    for channel in list(buffers.keys()):
                        await flush(channel) # flush the partial batches
                    break

                # Handle new packet
                if item is not False: # if a packet arrived in this iteration
                    packet, channel = item
                    if not buffers[channel]: # first packet of a new batch
                        first_seen[channel] = time.monotonic()
                    buffers[channel].append(_to_record(packet))

                    # If the buffer is full
                    if len(buffers[channel]) >= _BATCH_SIZE:
                        await flush(channel)

                # Publish any batch whose oldest packet has waited too long
                now = time.monotonic()
                for channel, t0 in list(first_seen.items()):
                    if now - t0 >= _FLUSH_TIMEOUT:
                        await flush(channel)
                
    finally:
        nm.stop_packet_capture(dumpcap_handler)

# MAIN ================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
