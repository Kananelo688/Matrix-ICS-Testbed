# MATRIX-ICS-TESTBED - SCADA Layer

# Table of Contents
- [File Tree](#file-tree)
- [Modules](#modules)
    - [Network Monitor](#network-monitor)

# File Tree
```
scada/
┣━ latency.py # (deprecated)
┣━ logger.py # (deprecated)
┣━ network_monitor.py # monitors network traffic via a SPAN port
┣━ opcua_client.py # (deprecated)
┣━ README.md # this file
┗━ requirements.txt # python dependencies for the SCADA layer
```

# Modules

| File Name | Local Dependencies | Purpose |
| :-- | :-- | :-- |
| `network_monitor.py` | None | Monitors network traffic via SPAN port |

---

## Network Monitor
### Overview
This module reads the network traffic on the TSW212 switch via the switch's port 6, which is configured as a SPAN port (all other ports are mirrored to this port). Packets are read using the `dumpcap` package, and saved to a `.pcap` file. This module can also, simultaneously, output the network log binaries, which can be piped to another module.

### Independent Usage
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
    Returns:
        subprocess.Popen: The handle for the open pipe to the `dumpcap` subprocess
    Raises:
        RuntimeError: If `dumpcap` fails to start
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
