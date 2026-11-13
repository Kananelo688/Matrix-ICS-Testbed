#!/usr/bin/env python3
"""
network_monitor.py

MATRIX Testbed - Network Traffic OPC-UA Server

OVERVIEW
    This module reads the network traffic on the TSW212 switch
    via the switch's port 6, which is configured as a SPAN port
    (all other ports are mirrored to this port). Packets are read
    using the `dumpcap` package, and saved to a `.pcap` file.
    This module can also, simultaneously, output the network log
    binaries, which can be piped to another module.

CLI USAGE
    To run this module independently, use:
        python network_monitor.py --id experiment_id

    The optional flags for the invocation are:
    - --description : free-text description for this run |
    - --iface : capture interface (device path or name from `dumpcap -D`) |
    - --results : directory to save result in |
    - -f : (no argument) forces saving data to the directory, without checking if data is being overwritten |

MODULE USAGE
    To run this module as an import for another Python program, use these functions:

    `start_packet_capture`
        Starts the `dumpcap` program as an asynchronous process, to monitor network traffic and write to a `.pcap` file
        Args:
            iface (str): The network interface that `dumpcap` monitors
            pcap_path (str): The file path to the target `.pcap` file
            log_path (str): The file path to the a target `.log` file for `dumpcap` logs
        Returns:
            subprocess.Popen: The handle for the open pipe to the `dumpcap` subprocess
        Raises:
            RuntimeError: If `dumpcap` fails to start

    `stop_packet_capture`
        Stops the `dumpcap` process cleanly
        Args:
            dumpcap_handle (subprocess.Popen): The handle for the open pipe to the `dumpcap` subprocess
        Raises:
            Exception: If failed to terminate `dumpcap`

Author : MATRIX / Intelligent Connectivity Group - UCT
"""

# IMPORTS ================================

# External
import sys
import argparse
import os
import signal
import subprocess
import time

# TYPES ================================

class _TeeStream:
    """
    File-like wrapper that makes whatever is read from the source also be written to the destination
    """
    def __init__(self, src, dst):
        self._src = src
        self._dst = dst

    def read(self, n=-1):
        data = self._src.read(n)
        if data:
            self._dst.write(data)
            self._dst.flush()
        return data

# CONSTANTS ================================

# Defaults
_DEFAULT_ARG_SPAN_NIC = r"\Device\NPF_{5BD8448F-DC4B-49B1-B53C-6A91DDAD0DDA}"
_DEFAULT_ARG_RESULTS = "results"

_SPAN_NIC_NAME = "Matrix-Monitoring-NIC"
_DUMPCAP = "dumpcap" # keyword to invoke `dumpcap` in the command line

# HELPER FUNCTIONS ================================

def _get_args() -> argparse.Namespace:
    """
    Builds a parser and parses the command-line arguments,
    using the `argparse` package.
    Returns:
        argparse.Namespace: The arguments form the CLI
    """
    parser = argparse.ArgumentParser(description="MATRIX network traffic monitor.")
    parser.add_argument("--id", required=True, help=
        "experiment id, e.g. 'baseline' or 'tm221_modbus_injection'"
    )
    parser.add_argument("--description", default="", help=
        "free-text description for this run"
    )
    parser.add_argument("--iface", default=_DEFAULT_ARG_SPAN_NIC, help=
        "capture interface (device path or name from `dumpcap -D`)"
    )
    parser.add_argument("--results", default=_DEFAULT_ARG_RESULTS, help=
        "directory to save result in"
    )
    parser.add_argument("-f", action="store_true", help=
        "forces saving data to the directory, without checking if data is being overwritten"
    )
    return parser.parse_args()
    
def _confirm_run_id(args:argparse.Namespace) -> bool:
    """
    Confirms the Run ID.
    If the Run ID is unique, or the `-f` flag is used, it is automatically confirmed.
    If a `.pcap` file with this Run ID already exists, then there's a risk of overwriting data,
    so a confirmation is required from the user, defaulting to cancelling
    Args:
        args (argparse.Namespace): The arguments from the CLI
    Returns:
        bool: Whether the Run ID was successfully confirmed or not
    """
    # Check for "force" flag
    if args.f:
        return True

    # Check if directory already exists
    dir_path = os.path.abspath(args.results)
    if not os.path.isdir(dir_path):
        return True # the directory doesn't exist, and therefore is safe
    
    # Get confirmation from user
    confirmation = input(f"The directory for this ID already exists:\n{dir_path}\nDo you want to overwrite data in this directory? [y/N]: ")
    return ( confirmation.lower() in ("y", "yes") )

def _print_args(args:argparse.Namespace):
    """
    Prints the parsed arguments to the terminal
    Args:
        args (argparse.Namespace): The arguments from the CLI
    """
    print(f"MATRIX Network Monitor")
    print(f"    run_id      : {args.id.strip()}")
    print(f"    description : {args.description or '(none)'}")
    print(f"    results dir : {os.path.abspath(os.path.abspath(args.results))}")
    print("Ctrl+C to end the run.")

def _get_file_paths(args:argparse.Namespace) -> tuple[str,str]:
    """
    Determines the file path to save the `.pcap` file
    Args:
        args (argparse.Namespace): The arguments from the CLI
    Returns:
        tuple[str,str]: The absolute path to the pcap and log files
    """
    run_id:str = args.id.strip()
    pcap_path = os.path.join(args.results, f"{run_id}.pcap")
    dumpcap_log = os.path.join(args.results, f"{run_id}_dumpcap.log")
    return (pcap_path, dumpcap_log)

# API FUNCTIONS ================================

def start_packet_capture(iface:str, pcap_path:str, log_path:str, stream:bool=False) -> subprocess.Popen:
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
    # Create directories and files
    os.makedirs(os.path.dirname(os.path.abspath(pcap_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")

    # Create the command for `dumpcap` and select the output
    """
    `-i` specifies the interface
    `-P` makes the output type classic pcap
    `-w` specifies what to write to (`-` is stdout)
    `-q` limits number of logs to reduce console noise
    """
    if stream: # if the data should be streamed, not only written to the file
        cmd = [_DUMPCAP, "-i", iface, "-P", "-w", "-", "-q"]
        stdout = subprocess.PIPE
    else:
        cmd = [_DUMPCAP, "-i", iface, "-P", "-w", pcap_path, "-q"]
        stdout = log_file

    # If on Windows, create a new process group, so Ctrl+C doesn't forcefully kill `dumpcap` as well
    if os.name == "nt": # if this is running on Windows
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creation_flags = 0
    dumpcap_handle = subprocess.Popen(cmd, stdout=stdout, stderr=log_file, creationflags=creation_flags)

    # Check if `dumpcap` terminated immediately, possibly due to a bad `iface` or lack of permissions
    time.sleep(1.0)
    if dumpcap_handle.poll() is not None: # if the dumpcap process terminated
        # Close the log file
        log_file.close()

        # Try to get last characters in the log file
        tail = ""
        try:
            with open(log_path, encoding="utf-8") as f:
                tail = f.read()[-500:] # get the last 500 characters of the file
        except Exception:
            pass

        # Raise RuntimeError
        raise RuntimeError(f"dumpcap exited immediately (rc={dumpcap_handle.returncode}).\n{tail}")

    # Modify the open pipe's handle to use a tee stream wrapper
    if stream: # if the data should be streamed, not only written to the file
        dumpcap_handle._pcap_file = open(pcap_path, "wb") # create a file member for the Tee Stream
        dumpcap_handle.stream = _TeeStream(dumpcap_handle.stdout, dumpcap_handle._pcap_file)

    # Return the open pipe's handle
    return dumpcap_handle

def stop_packet_capture(dumpcap_handle:subprocess.Popen):
    """
    Stops the `dumpcap` process cleanly
    Args:
        dumpcap_handle (subprocess.Popen): The handle for the open pipe to the `dumpcap` subprocess
    Raises:
        Exception: If failed to terminate `dumpcap`
    """
    # Check if the handle is invalid or `dumpcap` stopped for some other reason
    if (dumpcap_handle is None) or (dumpcap_handle.poll() is not None):
        return

    try:
        if os.name == "nt": # if this is running on Windows
            os.kill(dumpcap_handle.pid, signal.CTRL_BREAK_EVENT) # cleanly stop the process
        else:
            dumpcap_handle.send_signal(signal.SIGINT) # send an interrupt-signal
        dumpcap_handle.wait(timeout=5.0) # give the process 5 seconds to terminate

    # Terminating cleanly failed
    except Exception:
        try:
            # Forcefully terminate
            dumpcap_handle.terminate()
            dumpcap_handle.wait(timeout=3)
        except Exception as e:
            raise Exception(f"Could not stop dumpcap process:\n{e}")

    # Close the file pointer attached to the handle, used by the Tee Stream
    finally:
        file = getattr(dumpcap_handle, "_pcap_file", None)
        if file: # if there's a file pointer
            file.close()

# MAIN ================================

if __name__ == "__main__":
    try:
        # Note that `dumpcap` hasn't started yet
        dumpcap_active = False
        dumpcap_handle = None

        # Get arguments from CLI
        args = _get_args()
    
        # Verify Run ID
        confirmed = _confirm_run_id(args)
        if not confirmed:
            print("Cancelled")
            sys.exit(0)

        # Display arguments
        _print_args(args)

        # Start package capture
        try:
            dumpcap_handle = start_packet_capture(args.iface, *_get_file_paths(args))
        except Exception as e:
            print(f"Failed to start packet capture:\n{e}")
            sys.exit(2)
        dumpcap_active = True # not that dumpcap is running

        # Wait for termination
        while True:
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("Terminated")
        if dumpcap_active:
            try:
                stop_packet_capture(dumpcap_handle)
            except Exception as e:
                print(e)
