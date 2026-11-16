# MATRIX-ICS-TESTBED - SCADA Layer

# Table of Contents
- [Overview](#overview)
- [File Tree](#file-tree)
- [Installation & Dependencies](#installation--dependencies)
- [Modules](#modules)
    - [Network Monitor](#network-monitor)
    - [Packet Parser](#packet-parser)

# Overview
This subsystem monitors the network traffic at an interface (we recommend connecting it to a SPAN port),
and publishes the network traffic information via an OPC-UA server. Each network channel (a predefined destination and source IP/MAC, and vice versa)
is listed as its own OPC-UA variable node. The node stores a buffer of the network packets, which gets updated when:
- a new batch of 100 packets is available to be published
- a packet hasn't been published for over 2 seconds, triggering the entire channel to be published
- the packet stream from `dumpcap` fails/terminates, so the remaining packets are published

Packets are also saved to a classic `.pcap` file, in case using that for later analysis is easier.

To run this subsystem, use:
```bash
python opcua_server.py --id experiment_id
```
In the root of this repository, the command would be:
```bash
python src/net_traff_opcua/opcua_server.py --id experiment_id
```
The optional flags for the invocation are:
| Flag | Description |
| :-- | :-- |
| `--description` | free-text description for this run |
| `--iface` | capture interface (device path or name from `dumpcap -D`) |
| `--results` | directory to save result in |
| `-f` | (no argument) forces saving data to the directory, without checking if data is being overwritten |

# File Tree
```
net_traff_opcua/
┣━ network_monitor.py # monitors network traffic via a SPAN port
┣━ opcua_server.py # runs the OPC-UA server using information from the other two modules
┣━ packet_parser.py # parses a packet stream into OPC-UA nodes
┣━ README.md # this file
┗━ requirements_net_traff_opcua.txt # python dependencies for the SCADA layer
```

# Installation & Dependencies
The Python dependencies can be found in the [requirements file](requirements_net_traff_opcua.txt).
They can be installed using `pip`:
```bash
pip install -r requirements_net_traff_opcua.txt
```
In the root of this repository, the command would be:
```bash
pip install -r src/net_traff_opcua/requirements_net_traff_opcua.txt
```

# Modules
| File Name | Local Dependencies | Purpose |
| :-- | :-- | :-- |
| `network_monitor.py` | None | Monitors network traffic via a SPAN port |
| `packet_parser.py` | None | Parses a packet stream into OPC-UA nodes |

---

## Network Monitor
### Overview
This module reads the network traffic on the TSW212 switch via the switch's port 6, which is configured as a SPAN port (all other ports are mirrored to this port). Packets are read using the `dumpcap` package, and saved to a `.pcap` file. This module can also, simultaneously, output the network log binaries, which can be piped to another module.

### CLI Usage
To run this module independently, use:
```bash
python network_monitor.py --id experiment_id
```
The optional flags for the invocation are:
| Flag | Description |
| :-- | :-- |
| `--description` | free-text description for this run |
| `--iface` | capture interface (device path or name from `dumpcap -D`) |
| `--results` | directory to save result in |
| `-f` | (no argument) forces saving data to the directory, without checking if data is being overwritten |

### Module Usage
To run this module as an import for another Python program, use these functions:

```python
def start_packet_capture(iface:str, pcap_path:str, log_path:str) -> subprocess.Popen:
    """
    Starts the `dumpcap` program as an asynchronous process, to monitor network traffic and write to a `.pcap` file
    Args:
        iface (str): The network interface that `dumpcap` monitors
        pcap_path (str): The file path to the target `.pcap` file
        log_path (str): The file path to the a target `.log` file for `dumpcap` logs
        stream (bool): If the data should be streamed as well
    Returns:
        subprocess.Popen: The handle for the open pipe to the `dumpcap` subprocess
    Raises:
        RuntimeError: If `dumpcap` fails to start
    """
    ...
```

```python
def trusted_start():
    """
    Allows this module to handle the startup.
    This parses arguments and validates them the same way this module does, and forces a system exit upon failure.
    This function already calls `start_packet_capture()`, so another call would cause issues.
    Returns:
        subprocess.Popen: The handle for the open pipe to the `dumpcap` subprocess
    """
    ...
```

```python
def stop_packet_capture(dumpcap_handle:subprocess.Popen):
    """
    Stops the `dumpcap` process cleanly
    Args:
        dumpcap_handle (subprocess.Popen): The handle for the open pipe to the `dumpcap` subprocess
    Raises:
        Exception: If failed to terminate `dumpcap`
    """
    ...
```

## Packet Parser
### Overview
This module converts a file or stream of network packets into values that can be converted to OPC-UA nodes. It also groups the packets into channels (source and destination combinations), where the list of channels are defined as a constant inside the source code. It does so by extracting the packet parameters using `dpkt`, and returning the packet information along with the name of its corresponding channel.

### CLI Usage
To run this module on a `.pcap` file, you can use:
```bash
python packet_parser.py --file pcap_file_path | recipient_program
```
A stream of packets can be piped into this module:
```bash
packet_stream | python packet_parser.py | recipient_program
```
The `recipient_program` must expect JSON strings, in the format shown below:
```json
{
    "channel": ...,
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
```

### Module Usage
To run this module as an import for another Python program, use these functions:

```python
def get_channels() -> list[str]:
    """
    Gets the list of possible channels
    Returns:
        list[str]: The possible channel names
    """
    ...
```

```python
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
    ...
```

```python
def iter_packets(reader) -> Iterator[tuple[PacketInfo,str]]:
    """
    Yields a `PacketInfo` and channel `str` for every parseable packet in a `dpkt` reader
    Args:
        reader: The `dpkt` reader
    Yields:
        Iterator[tuple[PacketInfo,str]]: The parseable packets and their channel, from the reader
    """
    ...
```

An example, when using `network_monitor.py`, is shown below
```python
"""
Example program
"""

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
