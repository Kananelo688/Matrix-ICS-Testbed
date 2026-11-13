#!/usr/bin/env python3
"""
packet_parser.py

MATRIX Testbed - Network Traffic OPC-UA Server

OVERVIEW
    This module converts a file or stream of network packets
    into values that can be converted to OPC-UA nodes. It also
    groups the packets into channels (source and destination
    combinations), where the list of channels are defined as a
    constant inside the source code. It does so by extracting
    the packet parameters using `dpkt`, and returning the packet
    information along with the name of its corresponding channel.

CLI USAGE
    To run this module on a `.pcap` file, you can use:
        python packet_parser.py --file pcap_file_path | recipient_program
    
    A stream of packets can be piped into this module:
        packet_stream | python packet_parser.py | recipient_program
    
    The `recipient_program` must expect JSON strings, in the format shown below:
    {
        "group": ...,
        "packet": {
            "timestamp": ...,
            "length": ...,
            "src_mac": ...,
            "dst_mac": ...,
            "src_name": ...,
            "dst_name": ...,
            "src_ip": ...,
            "dst_ip": ...,
            "protocol": ...,
            "src_port": ...,
            "dst_port": ...,
        }
    }

MODULE USAGE
    To run this module as an import for another Python program, use these functions:

    `def get_channels`
        Gets the list of possible channels
        Returns:
            list[str]: The possible channel names
    
    `open_packet_source`
        Opens a packet source and wraps it in a `dpkt` reader.
        If no arguments are given, it the source is stdin
        Args:
            path (str|None): A pcap/pcapng file
            stream (BinaryIO|None): An already open binary stream. Live streams must be classic pcap, not pcapng
        Returns:
            tuple[BinaryIO,dpkt.pcap.UniversalReader]: (the open file/stream object, the dpkt reader). Close the file when done

    `iter_packets`
        Yields a `PacketInfo` and channel `str` for every parseable packet in a `dpkt` reader
        Args:
            reader: The `dpkt` reader
        Yields:
            Iterator[tuple[PacketInfo,str]]: The parseable packets and their channel, from the reader


    An example, when using `network_monitor.py`, is shown below
    ```
    import network_monitor as nm
    import packet_parser as pp

    handler = nm.start_packet_capture(iface, "results/run1.pcap", "results/run1_dumpcap.log", stream=True) # get live packet stream
    no_file, reader = pp.open_packet_source(stream=handler.stream) # handler.stream is the tee'd `dumpcap` stdout
    print("Channels: ", ", ".join(pp.get_channels()))

    try:
        for packet, channel in pp.iter_packets(reader):
            # blocks until a packet is available
            print(channel, packet.timestamp, packet.length)
    except KeyboardInterrupt:
        pass
    finally:
        nm.stop_packet_capture(h)
        # note that `no_file` isn't a file pointer, so it doesn't have to be closed
    ```
"""
         
# IMPORTS ================================

import argparse
import json
import socket
import sys
from dataclasses import asdict, dataclass
from typing import BinaryIO, Iterator
import dpkt

# TYPES ================================

@dataclass(frozen=True)
class _Endpoint:
    """
    Data Class to describe a networking endpoint.
    An Endpoint matches if it has the correct IP or MAC address
    """
    name:str
    ip:str = None
    mac:str = None  # lowercase, colon-separated: "aa:bb:cc:dd:ee:ff"

@dataclass
class PacketInfo:
    """
    The fields extracted from one packet
    """
    timestamp:float # capture time, seconds since epoch
    length:int # bytes on the wire (Ethernet frame)
    src_mac:str
    dst_mac:str
    src_name:str = None # endpoint name, filled in by `classify`
    dst_name:str = None # endpoint name, filled in by `classify`
    src_ip:str = None
    dst_ip:str = None
    protocol:str = "other" # "tcp" / "udp" / "icmp" / "arp" / "other"
    src_port:int = None
    dst_port:int = None

# CONSTANTS ================================

# Device names
_NAME_SCADA = "SCADA"
_NAME_MIDDLEWARE = "Middleware"
_NAME_SWITCH = "Switch"
_NAME_SCHNEIDER = "Schneider PLC"
_NAME_ALLEN_BRADLEY = "Allen-Bradley PLC"
_NAME_SIEMENS = "Siemens PLC"

# Known endpoints
_ENDPOINTS:list[_Endpoint] = [
    _Endpoint(_NAME_SCADA, ip="192.168.100.0/24"),
    _Endpoint(_NAME_MIDDLEWARE, ip="192.168.100.10"),
    _Endpoint(_NAME_SWITCH, ip="192.168.1.2"),
    _Endpoint(_NAME_SCHNEIDER, ip="192.168.50.50"),
    _Endpoint(_NAME_ALLEN_BRADLEY, ip="192.168.50.20"),
    _Endpoint(_NAME_SIEMENS, ip="192.168.50.10"),
]

# Network channels (order doesn't matter)
_CHANNELS:list[tuple[str,str]] = [
    (_NAME_SCADA, _NAME_MIDDLEWARE),
    (_NAME_MIDDLEWARE, _NAME_SCHNEIDER),
    (_NAME_MIDDLEWARE, _NAME_ALLEN_BRADLEY),
    (_NAME_MIDDLEWARE, _NAME_SIEMENS),
    (_NAME_SCHNEIDER, _NAME_ALLEN_BRADLEY),
    (_NAME_ALLEN_BRADLEY, _NAME_SCHNEIDER),
]
_UNKNOWN_CHANNEL:str = "Unknown"

# Channel look-up dict
_CHANNEL_LOOKUP:dict[frozenset,str]
for pair in _CHANNELS:
    _CHANNEL_LOOKUP[frozenset(pair)] = f"{pair[0]} <-> {pair[1]}"

# Protocol names
_PROTO_NAMES = {
    dpkt.ip.IP_PROTO_TCP: "tcp",
    dpkt.ip.IP_PROTO_UDP: "udp",
    dpkt.ip.IP_PROTO_ICMP: "icmp",
}

# HELPER FUNCTIONS ================================

def _get_args() -> argparse.Namespace:
    """
    Builds a parser and parses the command-line arguments,
    using the `argparse` package.
    Returns:
        argparse.Namespace: The arguments form the CLI
    """
    parser = argparse.ArgumentParser(description="MATRIX packet parser.")
    parser.add_argument("--file", default=None, help=
        "pcap/pcapng file to read (default: read a packet stream from stdin)"
    )
    return parser.parse_args()

def _format_mac(raw:bytes) -> str:
    """
    Converts a MAC address from bytes to a string
    Args:
        raw (bytes): The raw bytes
    Returns:
        str: A readable string
    """
    segments = []
    for byte in raw:
        segments.append(f"{byte:02x}")
    return ":".join(segments)

def _format_ip(raw:bytes) -> str:
    """
    Converts an IP address from bytes to a string
    Args:
        raw (bytes): The raw bytes
    Returns:
        str: A readable string
    """
    return socket.inet_ntoa(raw)

def _match_endpoint(ip:str|None, mac:str) -> str|None:
    """
    Gets the name of an endpoint using the IP or MAC address
    Args:
        ip (str|None): The IP address of the endpoint being searched for
        mac (str): The MAC address of the endpoint being searched for
    Returns:
        str|None: The name of the endpoint
    """
    for endpoint in _ENDPOINTS:
        if (endpoint.ip and endpoint.ip == ip) or (endpoint.mac and endpoint.mac == mac):
            return endpoint.name
    return None

def _classify(info:PacketInfo) -> str:
    """
    Fills the source and destination name,
    and gets the name of the channel that this packet belongs to
    Args:
        PacketInfo: The packet to classify
    Returns:
        str: The name of the channel
    """
    # Assume names were matched successfully
    success = True

    # Get the source and destination names
    info.src_name = _match_endpoint(info.src_ip, info.dst_mac)
    if info.src_name is None:
        info.src_name = ""
        success = False
    info.dst_name = _match_endpoint(info.dst_ip, info.dst_mac)
    if info.dst_name is None:
        info.dst_name = ""
        success = False

    # If the names were matched successfully, get the channel
    if success:
        channel = _CHANNEL_LOOKUP.get(frozenset((info.src_name, info.dst_name)))
        if channel is None:
            return _UNKNOWN_CHANNEL
        else:
            return channel
    
    # The name matching was unsuccessful
    return _UNKNOWN_CHANNEL

def _parse_packet(timestamp:float, buffer:bytes) -> tuple[PacketInfo,str]|None:
    """
    Extracts the relevant fields from one raw Ethernet frame
    Args:
        timestamp (float): Time since epoch in seconds
        buffer (bytes): Buffer of packet bytes
    Returns:
        tuple[PacketInfo,str]|None: (Information about the packet, The channel is belongs to)
    """
    # Try to parse into ethernet object
    try:
        eth = dpkt.ethernet.Ethernet(buffer)
    except (dpkt.UnpackError, dpkt.NeedData):
        return None

    # Initialise packet information
    info = PacketInfo(
        timestamp=timestamp,
        length=len(buffer),
        src_mac=_format_mac(eth.src),
        dst_mac=_format_mac(eth.dst),
    )

    # Set other members of the packet information
    if isinstance(eth.data, dpkt.ip.IP): # if the data uses IP
        ip = eth.data
        info.src_ip = _format_ip(ip.src)
        info.dst_ip = _format_ip(ip.dst)
        info.protocol = _PROTO_NAMES.get(ip.p, f"ip_{ip.p}")
        if isinstance(ip.data, (dpkt.tcp.TCP, dpkt.udp.UDP)): # if the protocol is TCP or UDP
            info.src_port = ip.data.sport
            info.dst_port = ip.data.dport
    elif isinstance(eth.data, dpkt.arp.ARP): #if the data uses ARP
        info.protocol = "arp"

    # Classify the packet
    channel = _classify(info)

    # Return
    return (info, channel)

# API FUNCTIONS ================================

def get_channels() -> list[str]:
    """
    Gets the list of possible channels
    Returns:
        list[str]: The possible channel names
    """
    return list(_CHANNEL_LOOKUP.values())+[_UNKNOWN_CHANNEL]

def open_packet_source(path:str|None=None, stream:BinaryIO|None=None) -> tuple[BinaryIO,dpkt.pcap.UniversalReader]:
    """
    Opens a packet source and wraps it in a `dpkt` reader.
    If no arguments are given, it the source is stdin
    Args:
        path (str|None): A pcap/pcapng file
        stream (BinaryIO|None): An already open binary stream. Live streams must be classic pcap, not pcapng
    Returns:
        tuple[BinaryIO,dpkt.pcap.UniversalReader]: (the open file/stream object, the dpkt reader). Close the file when done
    """
    if path:
        file = open(path, "rb")
    elif stream is not None:
        file = stream
    else:
        file = sys.stdin.buffer
    # UniversalReader auto-detects classic pcap vs pcapng
    return (file, dpkt.pcap.UniversalReader(file))

def iter_packets(reader) -> Iterator[tuple[PacketInfo,str]]:
    """
    Yields a `PacketInfo` and channel `str` for every parseable packet in a `dpkt` reader
    Args:
        reader: The `dpkt` reader
    Yields:
        Iterator[tuple[PacketInfo,str]]: The parseable packets and their channel, from the reader
    """
    for timestamp, buffer in reader:
        info_channel = _parse_packet(timestamp, buffer)
        if info_channel is not None:
            yield info_channel

# MAIN ================================

if __name__ == "__main__":
    args = _get_args()
    file, reader = open_packet_source(args.file)
    try:
        for packet, channel in iter_packets(reader):
            print(json.dumps({"channel":channel, "packet":asdict(packet)}), flush=True)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        if args.file:
            file.close()
