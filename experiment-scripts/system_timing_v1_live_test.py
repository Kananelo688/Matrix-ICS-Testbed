#!/usr/bin/env python3
"""
system_timing.py

MATRIX Testbed: This is the State Duration & Timing Logger
Captures real-time transitions (HIGH/LOW or True/False) for actuators and sensors
across all three zones, generating dynamic timestamp logs:
  - turntable_timing.csv
  - transfer_unit_timing.csv
  - conveyor_timing.csv

This script runs on-demand without modifying opcua_server.py by tapping directly
into the underlying client state dictionaries.
"""

import asyncio
import logging
import csv
import os
from datetime import datetime, timezone
from live_state_publisher import LiveStatePublisher

# Import client modules
try:
    import siemens_client
    import ab_cip_client
    import tm221_client
    _STANDALONE = False
except ImportError:
    _STANDALONE = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("SYSTEM_TIMING")

Monitored_Tags = {

    # Monitored Turntable FLAGS. (Key actuators and sensors for timing evaluation from Siemens S7-1200)
    "inPosition": "TurntableLimitSwitch",
    "magazineEmpty": "MagazineLightBarrier",
    "motorTurntable": "MotorTurntable",
    "drillActive": "MotorDrill",
    "weldActive": "WeldingLight",
    "sliderMagazine": "MagazineSlider",
    
    # Monitored Transfer Unit FLAGS. (Key actuators and sensors for timing evaluation from Allen-Bradley PLC)
    "rotateToTable": "RotateToTable",
    "rotateToConveyor": "RotateToConveyor",
    "vacuumGripper": "VacuumGripper",
    "transferUnitAtConveyor": "UnitAtConveyor",
    "transferUnitAtTurntable": "UnitAtTurntable",
    
    # Monitored Conveyor FLAGS. (Key actuators and sensors for timing evaluation from Arduino Opta)
    "sliderMotor": "SliderMotor",
    "conveyorBelt": "ConveyorBelt",
    "separatorValve": "SeparatorValve",
    "sliderInPosition": "SliderInPosition",
    "workpieceOnConveyor": "ConveyorLightBarrier",
    "workpieceOnPallet": "PalletLightBarrier",
}

ABSOLUTE_PATH = os.path.dirname(os.path.abspath(__file__)) # This script's directory path, used for CSV file output
#generated data is stored in ..\data\

# Handle standalone/mock mode if running locally for testing
if _STANDALONE:
    log.warning("Standalone mode — MOCK DATA ONLY; no real PLCs are connected")
    class _M: state = {}
    siemens_client = _M(); ab_cip_client = _M(); tm221_client = _M()
    siemens_client.state = {"motorTurntable": False, "drillActive": False, "inPosition": False}
    ab_cip_client.state = {"rotateToConveyor": False, "vacuumGripper": False}
    tm221_client.state = {"conveyorBelt": False, "workpieceOnConveyor": False}

class ZoneTimingLogger:
    def __init__(self, zone_name, client_module, csv_filename, publisher=None):
        self.zone_name = zone_name
        self.client_module = client_module
        self.csv_filename = csv_filename
        self.publisher = publisher
        
        # Tracks the last known state and transition timestamp of each tag
        # Structure: {tag_name: {"state": bool, "last_changed": datetime}}
        self.tracker = {}
        
        # Initialize CSV header file if it doesn't exist
        #if not os.path.exists(self.csv_filename): #TO DO: uncomment this check if you want to overwrite the file each time
        os.makedirs(os.path.dirname(self.csv_filename), exist_ok=True)
        with open(self.csv_filename, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Tag_Name", "State", "Duration_Sec"])

    def log_transition(self, tag, state, duration):
        """Appends a state transition row to the respective CSV file."""
        timestamp = datetime.now(timezone.utc).isoformat()
        state_str = "HIGH" if state else "LOW"
        try:
            with open(self.csv_filename, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, tag, state_str, f"{duration:.3f}"])
            log.info(f"[{self.zone_name}] {tag} turned {state_str} after {duration:.3f}s")
        except Exception as e:
            log.error(f"Failed writing to {self.csv_filename}: {e}")

    def flush_final_states(self):
        """Logs the still-ongoing state of every tracked tag up to the current time.
        Called when the timing loop stops, so the final HIGH/LOW segment of each
        tag (which never flipped again) still gets written to the CSV."""
        current_time = datetime.now(timezone.utc)
        for tag, info in self.tracker.items():
            label = Monitored_Tags.get(tag, tag)
            elapsed_seconds = (current_time - info["last_changed"]).total_seconds()
            self.log_transition(label, info["state"], elapsed_seconds)

    async def scan_and_update(self):
        """Scans the client's current memory space and detects changes."""
        current_time = datetime.now(timezone.utc)
        
        # Safe copy of state dictionary to prevent multi-threaded modification crashes
        current_state_dict = dict(self.client_module.state)
        
        for tag, current_val in current_state_dict.items():
            # Skip metadata keys like connection health strings
            if tag.startswith("_") or not isinstance(current_val, bool):
                continue
            if tag not in Monitored_Tags:
                #log.warning(f"[{self.zone_name}] Unmonitored tag '{tag}' detected; skipping.")
                continue

            label = Monitored_Tags[tag]

            if tag not in self.tracker:
                # First time seeing this tag, map baseline
                self.tracker[tag] = {
                    "state": current_val,
                    "last_changed": current_time
                }
                continue
            
            # State flip detected
            if current_val != self.tracker[tag]["state"]:
                prev_time = self.tracker[tag]["last_changed"]
                elapsed_seconds = (current_time - prev_time).total_seconds()
                
                # Log the completed duration of the PREVIOUS state
                self.log_transition(label, self.tracker[tag]["state"], elapsed_seconds)
                
                # Update tracker with the new current state
                self.tracker[tag] = {
                    "state": current_val,
                    "last_changed": current_time
                }
                if self.publisher is not None:
                    await self.publisher.publish(self.zone_name, label, current_val)

async def timing_engine_loop(interval=0.1):
    """Scan existing PLC dictionaries, log CSV, and publish FU3 live changes."""
    log.info("Starting System Timing Engine tracking loop...")

    publisher = LiveStatePublisher(host="127.0.0.1", port=55001)
    loggers = [
        ZoneTimingLogger("Turntable", siemens_client, os.path.join(ABSOLUTE_PATH, "..", "data", "timing_dataset", "live_test_turntable_timing.csv")),
        ZoneTimingLogger("TransferUnit", ab_cip_client, os.path.join(ABSOLUTE_PATH, "..", "data", "timing_dataset", "live_test_transfer_unit_timing.csv")),
        ZoneTimingLogger("Conveyor", tm221_client, os.path.join(ABSOLUTE_PATH, "..", "data", "timing_dataset", "live_test_conveyor_timing.csv"), publisher=publisher),
    ]

    # Give newly connected receivers the current known FU3 state.
    def snapshot():
        fu3 = loggers[2]
        return [(fu3.zone_name, Monitored_Tags[tag], info["state"])
                for tag, info in fu3.tracker.items()]

    publisher.snapshot_provider = snapshot
    await publisher.start()
    try:
        while True:
            for logger in loggers:
                await logger.scan_and_update()
            await asyncio.sleep(interval)
    finally:
        for logger in loggers:
            logger.flush_final_states()
        await publisher.close()
        log.info("Timing Engine loop stopped")


async def start(scan_interval_seconds=0.1):
    """
    Exposed entry point function to launch the timing data generation pipeline.
    Call this function from an external supervisor script or command line.
    """
    try:
        await timing_engine_loop(interval=scan_interval_seconds)
    except KeyboardInterrupt:
        log.info("Timing evaluation terminated by user interface.")

async def run():
    log.info("MATRIX middleware starting...")
    log.info("  Task 1 : Siemens S7-1200  OPC-UA client")
    log.info("  Task 2 : Allen-Bradley    EtherNet/IP (CIP) client")
    log.info("  Task 3 : Schneider TM221  Modbus TCP client")
    log.info("  Task 4 : OPC-UA server    → Ignition SCADA")

    tasks = await asyncio.gather(
        siemens_client.run(), #type:ignore
        ab_cip_client.run(), #type:ignore
        tm221_client.run(), #type:ignore
        start(),
        return_exceptions=True
    )

    for i, result in enumerate(tasks):
        if isinstance(result, Exception):
            log.error(f"Task {i+1} exited with error: {result}")

    # If run directly as a script, start tracking immediately

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("System Timing Engine terminated by user interface.")