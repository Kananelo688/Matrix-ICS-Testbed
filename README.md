# MATRIX — Multi-vendor Automation Testbed for Research in ICS Security

**University of Cape Town · Intelligent Connectivity Group**

MATRIX is a physical, heterogeneous Industrial Control System (ICS) and Cyber-Physical System (CPS) security research testbed. It brings together controllers from three different vendors — Siemens, Rockwell Automation (Allen-Bradley), and Arduino — each governing a dedicated stage of a shared Fischertechnik 24V production line. The testbed is designed to study the security implications of multi-vendor, multi-protocol industrial environments: the kind of environment found in real plants, but rarely reproduced in research settings.

---

## Table of Contents

- [What MATRIX is](#what-matrix-is)
- [Physical plant — the Fischertechnik 24V production line](#physical-plant)
- [System architecture](#system-architecture)
- [Controllers](#controllers)
- [Communication protocols](#communication-protocols)
  - [Modbus TCP — Level 1 peer-to-peer](#modbus-tcp)
  - [S7comm — Siemens to middleware](#s7comm)
  - [EtherNet/IP — Allen-Bradley to middleware](#ethernetip)
  - [OPC-UA — middleware to SCADA](#opc-ua)
- [Middleware — Raspberry Pi protocol bridge](#middleware)
- [SCADA — Ignition Perspective](#scada)
- [Security monitoring](#security-monitoring)
- [Research focus areas](#research-focus-areas)
- [Network topology](#network-topology)
- [Tag reference](#tag-reference)
- [Repository structure](#repository-structure)
- [Publications](#publications)

---

## What MATRIX is

Most ICS security research relies on testbeds built around a single vendor or a single protocol. MATRIX deliberately rejects that simplification. In real industrial plants, equipment from multiple vendors — each speaking its own proprietary protocol, each with different security characteristics — must work together to control a single physical process. The security consequences of that heterogeneity are under-studied.

MATRIX addresses this by deploying three co-equal controllers from different vendors over one shared physical plant. Each controller owns one production stage and must coordinate with the others to keep the process running. This makes cross-vendor peer-to-peer communication an operational requirement rather than an optional feature, and exposes a set of security problems that homogeneous testbeds cannot reproduce:

- A compromised controller can inject false handoff signals that cause physical process failures in a different vendor's stage
- Each vendor's Modbus implementation behaves differently under identical attack conditions
- The security boundary between proprietary firmware (Siemens, Allen-Bradley) and open-source firmware (Arduino Opta) introduces attack surfaces that are largely unstudied
- Protocol translation at the middleware layer creates a natural micro-segmentation boundary whose security properties can be systematically evaluated

---

## Physical plant

The Fischertechnik 24V production line is a laboratory-scale manufacturing system consisting of three mechanically linked subsystems. A workpiece enters at the turntable, is processed through drilling and welding stations, is transferred to the conveyor belt, and is eventually palletised. The full I/O complement is 8 sensors and 10 actuators, all operating on 24VDC digital signals.

### Turntable (controlled by Siemens S7-1200)

The rotary table has four stations arranged in a 90° index sequence. A workpiece from the magazine (Station 1) progresses through drilling (Station 2), welding (Station 3), and handover to the transfer unit (Station 4). The table may only rotate when no process is active and the transfer unit is clear.

| Signal | Type | Description |
|---|---|---|
| S4 (I6) | Digital input | Rotary table in position (normally open) |
| B4 (I8) | Digital input | Light barrier magazine — 0 = workpiece present |
| Q4 | Digital output | Motor turntable (clockwise rotation) |
| Q7 | Digital output | Valve magazine slider (pushes workpiece onto table) |
| Q9 | Digital output | Motor drill (3 second process) |
| Q10 | Digital output | Welding lamp (5 second process) |

### Transfer unit (controlled by Allen-Bradley Micro820)

The transfer unit is a bidirectional motorised arm with a vacuum gripper. It collects finished workpieces from the turntable's handover station and deposits them on the conveyor belt. End positions are monitored by limit switches that interlock movement to prevent motor overload.

| Signal | Type | Description |
|---|---|---|
| S1 (I1) | Digital input | Limit switch — conveyor belt end position |
| S2 (I2) | Digital input | Limit switch — turntable end position |
| Q1 | Digital output | Motor — move toward turntable |
| Q2 | Digital output | Motor — move toward conveyor belt |
| Q8 | Digital output | Vacuum valve (gripper on/off) |

### Conveyor belt (controlled by Arduino Opta)

The conveyor receives workpieces from the transfer unit and transports them to a palletising station. Three workpieces are accumulated before a pusher ejects them onto a waiting pallet. A separator prevents belt movement during ejection.

| Signal | Type | Description |
|---|---|---|
| S3 (I3) | Digital input | Limit switch — slider home position |
| B1 (I4) | Digital input | Light barrier — workpiece on belt |
| B2 (I5) | Digital input | Light barrier — pallet top (workpieces present on pallet) |
| B3 (I7) | Digital input | Light barrier — pallet bottom (pallet present) |
| Q3 | Digital output | Motor pusher (palletising stroke) |
| Q5 | Digital output | Motor belt |
| Q6 | Digital output | Valve separator |

---

## System architecture

MATRIX implements the Purdue Model reference architecture across three network zones:

```
┌─────────────────────────────────────────────────────────────┐
│  LEVEL 2 — Supervision  (VLAN 30: 192.168.30.0/24)         │
│                                                             │
│   ┌──────────────────┐    OPC-UA/TLS    ┌───────────────┐  │
│   │  Raspberry Pi 2  │ ◄─────────────► │  Ignition     │  │
│   │  Middleware       │   port 4840     │  SCADA        │  │
│   │  OPC-UA Server   │                 │  Perspective  │  │
│   │  Modbus Client   │                 │  HMI          │  │
│   │  EtherNet/IP Cl. │                 └───────────────┘  │
│   └────────┬─────────┘                                     │
└────────────┼────────────────────────────────────────────────┘
             │ Protocol translation boundary (micro-segmentation)
┌────────────┼────────────────────────────────────────────────┐
│  LEVEL 1 — Control  (VLAN 20: 192.168.20.0/24)             │
│            │                                                │
│   ┌────────▼──────┐  Modbus TCP  ┌────────────────┐        │
│   │ Siemens       │ ◄──────────► │ Allen-Bradley  │        │
│   │ S7-1200       │  port 502    │ Micro820       │        │
│   │ Stage 1       │              │ Stage 2        │        │
│   │ (Turntable)   │              │ (Transfer unit)│        │
│   └───────────────┘              └───────┬────────┘        │
│                                          │ Modbus TCP       │
│                                          │ port 502         │
│                                   ┌──────▼────────┐        │
│                                   │ Arduino Opta  │        │
│                                   │ Stage 3       │        │
│                                   │ (Conveyor)    │        │
│                                   └───────────────┘        │
└─────────────────────────────────────────────────────────────┘
             │ 24VDC I/O (electrical signals only)
┌────────────┼────────────────────────────────────────────────┐
│  LEVEL 0 — Physical process                                 │
│   Fischertechnik 24V production line                        │
│   [Turntable] ──► [Transfer unit] ──► [Conveyor belt]      │
└─────────────────────────────────────────────────────────────┘
```

No raw ICS protocol traffic crosses the Level 1 / Level 2 boundary. All such traffic terminates at the Raspberry Pi middleware, which re-exposes aggregated process data as OPC-UA to the supervision layer. This enforces micro-segmentation as a zero-trust architectural principle.

---

## Controllers

### Siemens S7-1200 (CPU 1214C DC/DC/DC)

- **Programming environment:** TIA Portal V19
- **Programming language:** Ladder Diagram (LAD)
- **IP address:** `192.168.20.10`
- **Role:** Process initiator. Controls turntable rotation and all four station operations. Holds the workpiece state data block tracking each nest's occupancy (magazine part, drilling raw/finished, welding raw/finished, transfer ready).
- **Protocols:** S7comm (port 102) for middleware communication; Modbus TCP client (port 502) for peer communication with Allen-Bradley. OPC-UA server capability available on this firmware but not used at Level 1 in the current configuration.
- **Key configuration:** PUT/GET communication enabled in TIA Portal device properties to allow external Modbus and S7comm access. Optimised block access disabled on the workpiece data block to permit raw register reads by security monitoring tools.

### Allen-Bradley Micro820 (2080-LC20-20QBB)

- **Programming environment:** Connected Components Workbench (CCW)
- **Programming language:** Ladder Diagram
- **IP address:** `192.168.20.20`
- **Role:** Transfer unit controller. Manages the bidirectional motorised arm and vacuum gripper, with interlocking logic that prevents motor overload at end positions. Receives handoff signals from the Siemens S7-1200 and sends ready signals to the Arduino Opta.
- **Protocols:** EtherNet/IP (port 44818) for middleware communication; Modbus TCP server (port 502) for Level 1 peer communication. Modbus TCP is enabled via the CCW Modbus mapping panel where controller variables are explicitly mapped to coil/register addresses.
- **Key configuration:** Modbus TCP server enabled in CCW with explicit variable mapping. EtherNet/IP CIP identity object is accessible unauthenticated — enumerable by nmap and serves as a vulnerability assessment target.
- **Limitation:** The Micro820 does not expose a symbolic tag database via EtherNet/IP in the way a full ControlLogix/CompactLogix does. CIP explicit messaging is used for identity queries; data exchange uses Modbus TCP.

### Arduino Opta (AFX00007 + digital expansion module)

- **Programming environment:** Arduino PLC IDE
- **Programming language:** IEC 61131-3 Ladder Diagram
- **IP address:** `192.168.20.30`
- **Role:** Conveyor belt controller and process terminator. Manages belt movement, workpiece counting, separator control, and palletising sequence. Signals the Siemens S7-1200 when the palletising cycle completes and the process can restart.
- **Protocols:** Modbus TCP server (port 502) only. Physical output variables (`%QX0.0` etc.) are automatically mapped to Modbus coil addresses by the PLC IDE runtime — no manual register configuration required.
- **Key differentiator:** The Opta is open-source and community-maintained. Its firmware is fully inspectable and modifiable, making it a uniquely flexible research asset. It can be deliberately misconfigured or programmed to simulate a compromised field device in ways that are not achievable with proprietary PLCs. The security implications of co-locating open-source firmware with proprietary PLCs in the same control network are a primary research interest of this testbed.

---

## Communication protocols

### Modbus TCP

**Standard:** Modbus Application Protocol Specification V1.1b3 (Modbus.org, 2012)
**Port:** 502 (TCP)
**OSI layer:** Application (Layer 7) over TCP/IP (Layer 4/3)
**Purdue zone:** Level 1 peer-to-peer communication

Modbus TCP is the universal protocol of MATRIX's control layer. All three controllers support it, making it the only protocol that can serve as a common language for cross-vendor peer coordination. The protocol was designed in 1979 with no security mechanisms; Modbus TCP inherits this design and adds only a minimal Application Data Unit (ADU) header over TCP — no authentication, no encryption, and no message integrity protection.

**How it works in MATRIX:**

The three controllers form a directed ring topology. Each controller acts simultaneously as a Modbus TCP server (exposing its own process state) and as a Modbus TCP client (writing handoff signals to the next stage):

```
S7-1200 (client) ──── writes coil ────► Micro820 (server)
Micro820 (client) ─── writes coil ────► Opta (server)
Opta (client) ──────── writes coil ────► S7-1200 (server)
```

A handoff signal is a single Modbus coil write (function code 0x05). When Stage 1 completes a turntable index and the transfer unit is clear, the S7-1200 writes `Coil 0 = TRUE` to the Micro820, which interprets this as permission to begin the transfer sequence. When the transfer unit has deposited a workpiece on the belt, the Micro820 writes `Coil 0 = TRUE` to the Opta. When the Opta completes a palletising cycle, it writes `Coil 0 = TRUE` back to the S7-1200.

**Data model used:**

| Modbus table | Address range | Usage in MATRIX |
|---|---|---|
| Coils (0x) | 0–9 | Handoff signals, actuator commands (Boolean) |
| Holding Registers (4x) | 0–19 | Process state values, workpiece counts, timer states |
| Discrete Inputs (1x) | 0–9 | Sensor states (read-only from PLC perspective) |

**Security characteristics:**

Any device on VLAN 20 can read or write any register on any controller using standard Modbus TCP packets. There is no mechanism for a controller to verify the source of a write request. This makes the Level 1 network an intentionally exposed attack surface for the following experiment categories:

- **False data injection:** A monitoring node on VLAN 40 can write arbitrary coil values to any controller, simulating a compromised upstream peer sending false handoff signals
- **Replay attacks:** Captured Modbus TCP packet sequences can be replayed without modification — there is no sequence number or timestamp in the payload
- **Reconnaissance:** Function code 0x2B (Read Device Identification) returns vendor name, product name, and firmware version from the Opta without authentication. The Siemens S7-1200 exposes similar information via S7comm
- **Unauthorised command injection:** Any device that can route packets to port 502 can command actuators directly, bypassing PLC logic entirely

**Implementation notes:**
- Siemens S7-1200: Modbus TCP client implemented using the `MB_CLIENT` function block in TIA Portal. Configured as a non-persistent connection with a polling interval of 100ms
- Allen-Bradley Micro820: Modbus TCP server enabled via the CCW Modbus mapping panel. Client functionality uses the `MBSTCP` instruction in ladder logic
- Arduino Opta: Modbus TCP server is the native communication mode of the PLC IDE runtime. Client functionality implemented in a separate ladder rung using the PLC IDE Modbus client function block

---

### S7comm

**Reference:** Reverse-engineered specification — Wireshark S7comm dissector documentation; Thomas Wiens (GitHub); Klick et al. (2014)
**Port:** 102 (TCP — ISO Transport Service Access Point, RFC 1006)
**OSI layer:** Application (Layer 7) over ISO-TSAP session (Layer 5) over TCP (Layer 4)
**Purdue zone:** Level 1 to Level 2 — Siemens S7-1200 to Raspberry Pi middleware

S7comm is Siemens' proprietary industrial protocol. Unlike Modbus TCP, it was never formally published — the specification was reverse-engineered by the security research community, principally through Wireshark plugin development and post-Stuxnet analysis. The protocol uses ISO-TSAP as a session layer beneath TCP, which means it does not use standard application ports and is frequently missed by firewalls that filter only ports 80, 443, and 8080.

**How it works in MATRIX:**

The Raspberry Pi middleware connects to the S7-1200 as an S7comm client using the `python-snap7` library. It reads the workpiece state data block (DB1) and process image values at a configurable polling interval (default 500ms). The data block address space is:

```
DB1.DBX0.0  — turntable_in_position (BOOL)
DB1.DBX0.1  — magazine_empty (BOOL)
DB1.DBX0.2  — motor_turntable (BOOL)
DB1.DBX0.3  — drill_active (BOOL)
DB1.DBX0.4  — weld_active (BOOL)
DB1.DBX0.5  — slider_magazine (BOOL)
DB1.DBW2    — turntable_position_index (INT, 0–3)
DB1.DBX4.0  — magazinePart (BOOL)
DB1.DBX4.1  — drillingRawPart (BOOL)
DB1.DBX4.2  — drillingFinishedPart (BOOL)
DB1.DBX4.3  — weldingRawPart (BOOL)
DB1.DBX4.4  — weldingFinishedPart (BOOL)
DB1.DBX4.5  — transferPart (BOOL)
```

**Security characteristics:**

The S7-1200 (firmware v4.x) has no authentication on S7comm connections by default. Any host that can reach port 102 can read all memory areas and data blocks, and write to outputs. The `plcscan` tool can enumerate CPU type, order number, firmware version, and installed function blocks without credentials. Metasploit's `auxiliary/scanner/scada/siemens_s7_cpu_stop` module can halt the PLC entirely using a crafted S7comm packet.

S7comm+ (introduced with S7-1500) adds optional TLS and certificate-based authentication but is not available on the S7-1200. This firmware limitation is documented in the testbed and is relevant to the vulnerability assessment experiments.

---

### EtherNet/IP (Common Industrial Protocol)

**Standard:** ODVA — EtherNet/IP Specification; IEC 61784-2
**Ports:** 44818 (TCP — explicit messaging); 2222 (UDP — implicit I/O messaging)
**OSI layer:** CIP Application (Layer 7) over TCP/UDP (Layer 4)
**Purdue zone:** Level 1 to Level 2 — Allen-Bradley Micro820 to Raspberry Pi middleware

EtherNet/IP transports the Common Industrial Protocol (CIP), an object-oriented application layer developed by ODVA. The Raspberry Pi middleware uses the `pycomm3` library to send CIP explicit messages to the Micro820 for device identification and status reads. Full tag-by-name access (available on ControlLogix/CompactLogix) is not supported on the Micro820 — only CIP identity object queries and generic explicit messaging are used in MATRIX.

**How it works in MATRIX:**

The middleware sends a CIP `List Identity` broadcast to enumerate the Micro820 on startup, confirming device presence and firmware version. Runtime data exchange uses Modbus TCP rather than EtherNet/IP, because the Micro820's CIP implementation does not expose a controller tag database in the way a full Logix5000 platform does. EtherNet/IP in MATRIX therefore serves two purposes: device fingerprinting during vulnerability assessment experiments, and a demonstration of the protocol's identity exposure characteristics.

**Security characteristics:**

The CIP `List Identity` service (UDP port 44818) responds to broadcast queries with vendor ID, device type, product code, revision, serial number, and product name — all unauthenticated. CIP Security (TLS + mutual authentication) was added by ODVA in 2016 but is not implemented on the Micro820. There is no mechanism to authenticate the source of explicit CIP messages.

---

### OPC-UA

**Standard:** OPC Foundation — OPC UA Specification Parts 1–14; IEC 62541 series
**Port:** 4840 (TCP — binary encoding)
**OSI layer:** Application (Layer 7) with optional TLS (Layer 6) over TCP (Layer 4)
**Purdue zone:** Level 2 — Raspberry Pi middleware to Ignition SCADA

OPC-UA is the only protocol in MATRIX designed with security as a first principle. It provides mutual X.509 certificate authentication, TLS 1.2/1.3 encryption, message signing, and user-level access control. It is the sole protocol permitted to cross the Level 1 / Level 2 network boundary — no Modbus TCP, S7comm, or EtherNet/IP traffic reaches the supervision network.

**How it works in MATRIX:**

The Raspberry Pi middleware runs an OPC-UA server using the `asyncua` Python library. It aggregates all process data polled from the three controllers (via Modbus TCP, S7comm, and EtherNet/IP respectively) and exposes them as a unified OPC-UA address space organised by plant zone:

```
MATRIX/
├── Turntable/
│   ├── turntable_in_position   Boolean
│   ├── magazine_empty          Boolean
│   ├── motor_turntable         Boolean
│   ├── drill_active            Boolean
│   ├── weld_active             Boolean
│   ├── slider_magazine         Boolean
│   ├── turntable_index         Int16
│   ├── magazinePart            Boolean
│   ├── drillingFinishedPart    Boolean
│   ├── weldingFinishedPart     Boolean
│   └── transferPart            Boolean
├── TransferUnit/
│   ├── conv_end_position       Boolean
│   ├── table_end_position      Boolean
│   ├── move_to_table           Boolean
│   ├── move_to_belt            Boolean
│   └── vacuum_gripper          Boolean
└── Conveyor/
    ├── workpiece_on_belt       Boolean
    ├── pallet_top              Boolean
    ├── pallet_ready            Boolean
    ├── slider_home             Boolean
    ├── motor_belt              Boolean
    ├── separator               Boolean
    ├── pusher                  Boolean
    └── workpiece_count         Int16
```

Ignition connects to this OPC-UA server as a client, subscribes to all nodes, and receives change notifications at configurable rates. The historian logs every value change with millisecond timestamps — this time-series database is the primary ground-truth dataset for anomaly detection experiments.

**Security characteristics (compared to Level 1 protocols):**

| Property | Modbus TCP | S7comm | EtherNet/IP | OPC-UA |
|---|---|---|---|---|
| Authentication | None | None | None | X.509 certificates |
| Encryption | None | None | None | TLS 1.2/1.3 |
| Message integrity | None | None | None | Signed messages |
| Access control | None | None | None | User-level policies |
| Port | 502 | 102 | 44818 | 4840 |

The contrast between the Level 1 protocols (all lacking security) and OPC-UA (security-capable by design) is the basis for the protocol security comparison experiment.

---

## Middleware

The Raspberry Pi 2 middleware node is the architectural boundary between the control and supervision networks. It performs three functions simultaneously:

1. **Protocol client (Level 1 facing):** Polls the S7-1200 via S7comm, the Micro820 via EtherNet/IP (identity) and Modbus TCP (data), and the Opta via Modbus TCP. Three concurrent Python async tasks, one per controller.

2. **Data aggregation:** Normalises all polled values into a shared in-memory process state dictionary, keyed by the OPC-UA node paths shown above.

3. **OPC-UA server (Level 2 facing):** Exposes the aggregated state as an OPC-UA server on port 4840. Ignition subscribes to this server and receives updates whenever values change.

This architecture means no raw ICS protocol traffic ever reaches VLAN 30. An attacker who compromises a Modbus TCP link on VLAN 20 cannot directly reach the SCADA historian — they must first pivot through the middleware node, which is the only host with interfaces on both VLANs. This is the micro-segmentation property that MATRIX is designed to evaluate.

**Hardware:** Raspberry Pi 2 Model B — one built-in Ethernet interface (VLAN 20, control-facing) and one USB-to-Ethernet adapter (VLAN 30, supervision-facing).

**Software stack:**
- OS: Raspberry Pi OS Lite (64-bit)
- `asyncua` — OPC-UA server and Siemens OPC-UA client
- `python-snap7` — S7comm client for S7-1200
- `pycomm3` — EtherNet/IP CIP client for Micro820
- `pymodbus` — Modbus TCP client for all three controllers

---

## SCADA

Ignition SCADA (Inductive Automation) runs on a dedicated PC in VLAN 30. It connects to the middleware OPC-UA server and provides three research-relevant functions:

- **Perspective HMI:** A web-based operator interface displaying real-time plant state across all three stages, including individual sensor and actuator status, workpiece tracking variables, and a live production line view
- **Historian:** A millisecond-resolution time-series database logging every OPC-UA tag value change. This is the ground-truth dataset for all anomaly detection experiments — the baseline period is 24–48 hours of normal operation before any attack injection
- **Alarm pipeline:** Configurable threshold-based alarms. Example: `magazine_empty = TRUE` triggers a magazine alarm; unexpected `motor_belt = TRUE` while `workpiece_on_belt = FALSE` may indicate a false start condition

---

## Security monitoring

A dedicated security monitoring node is connected to a SPAN port on the managed switch, passively mirroring all traffic from VLAN 20 without injecting packets into the control network.

**Tools:**
- **Zeek** — generates structured logs per protocol: `modbus.log` (function codes, register addresses, values), `enip.log` (CIP service codes), `opcua.log` (subscription updates). These logs are the primary input for anomaly detection models
- **Wireshark** — packet-level inspection and protocol dissection. Wireshark fully decodes Modbus TCP and EtherNet/IP from VLAN 20 traffic; OPC-UA on VLAN 30 is encrypted (TLS) and not readable without the server's private key — demonstrating the OPC-UA security boundary in practice
- **Snort/Suricata** — signature-based IDS. Custom rules flag unexpected Modbus function codes (e.g. FC 0x05 writes from unrecognised source IPs) and S7comm CPU stop commands

---

## Research focus areas

### 1. Cyber-physical anomaly detection (primary)

A Timed Automaton implemented in MATLAB Stateflow monitors the Zeek Modbus TCP logs for deviations from expected event sequences. Normal operation has deterministic timing boundaries: turntable index takes 2–3 seconds, drilling takes 3 seconds, welding takes 5 seconds, transfer takes 4–6 seconds. Events outside these temporal bounds — or events in unexpected sequence — trigger the IDS. The multi-vendor environment is essential here: each vendor's Modbus implementation produces subtly different traffic timing, so the baseline model must be vendor-aware.

### 2. Vulnerability assessment and protocol fingerprinting

Each controller is scanned from the security monitoring node using `nmap` ICS NSE scripts, `plcscan`, and Metasploit's EtherNet/IP and S7comm modules. The experiment documents what each vendor exposes unauthenticated, across three different proprietary platforms in a single scan session. This extends single-vendor assessment frameworks to live heterogeneous physical hardware.

### 3. Protocol security comparison

Modbus TCP (Level 1, no security) and OPC-UA with TLS (Level 2, full security) are benchmarked on the same data path. Metrics: round-trip latency, CPU overhead on the Raspberry Pi, and traffic volume per unit of process data transferred. The presence of the middleware in the measurement path allows an end-to-end comparison across the full protocol stack from field device to SCADA historian.

### 4. Resilience and cross-vendor fault propagation

The S7-1200 is halted using Metasploit's `s7_300_400_cpu_stop` module. The experiment observes how the Stage 1 fault propagates through the shared physical process: does the Allen-Bradley detect the missing handoff signal? Does the Opta continue running the conveyor independently? Does the Ignition historian correctly timestamp the event? Because all three controllers share one physical plant, a Stage 1 fault has immediate, measurable physical consequences at Stages 2 and 3 — propagation dynamics that testbeds with independent per-PLC subsystems cannot reproduce.

---

## Network topology

| Device | VLAN | IP address | Role |
|---|---|---|---|
| Dedicated PC (NIC1) | Campus LAN | DHCP | Internet, licensing |
| Dedicated PC (NIC2) | VLAN 20 | 192.168.20.1 | Engineering workstation |
| Siemens S7-1200 | VLAN 20 | 192.168.20.10 | Stage 1 controller |
| Allen-Bradley Micro820 | VLAN 20 | 192.168.20.20 | Stage 2 controller |
| Arduino Opta | VLAN 20 | 192.168.20.30 | Stage 3 controller |
| Raspberry Pi 2 (eth0) | VLAN 20 | 192.168.20.100 | Middleware — control facing |
| Raspberry Pi 2 (eth1) | VLAN 30 | 192.168.30.100 | Middleware — supervision facing |
| Ignition SCADA PC | VLAN 30 | 192.168.30.10 | Supervision and historian |
| Security monitoring node | VLAN 40 | 192.168.40.10 | Zeek, Wireshark, Snort |

---

## Tag reference

Full I/O tag reference derived from the Fischertechnik 24V production line terminal strip assignment (Table X1, ST1, ST2).

| Tag name | Physical signal | Controller | Type | Description |
|---|---|---|---|---|
| `turntable_in_position` | S4 (I6) | S7-1200 | Input | Rotary table aligned — normally open contact |
| `magazine_empty` | B4 (I8) | S7-1200 | Input | Light barrier magazine — 0 = workpiece present |
| `motor_turntable` | Q4 | S7-1200 | Output | Table rotation motor |
| `slider_magazine` | Q7 | S7-1200 | Output | Magazine slider valve |
| `drill_active` | Q9 | S7-1200 | Output | Drill motor (3 second operation) |
| `weld_active` | Q10 | S7-1200 | Output | Welding lamp (5 second operation) |
| `magazinePart` | — | S7-1200 | DB flag | Nest 1 occupied |
| `drillingRawPart` | — | S7-1200 | DB flag | Nest 2 has undrilled workpiece |
| `drillingFinishedPart` | — | S7-1200 | DB flag | Nest 2 has drilled workpiece |
| `weldingRawPart` | — | S7-1200 | DB flag | Nest 3 has unwelded workpiece |
| `weldingFinishedPart` | — | S7-1200 | DB flag | Nest 3 has welded workpiece |
| `transferPart` | — | S7-1200 | DB flag | Nest 4 has finished workpiece ready for pickup |
| `conv_end_position` | S1 (I1) | Micro820 | Input | Transfer unit at conveyor belt end |
| `table_end_position` | S2 (I2) | Micro820 | Input | Transfer unit at turntable end |
| `move_to_table` | Q1 | Micro820 | Output | Transfer unit motor — toward turntable |
| `move_to_belt` | Q2 | Micro820 | Output | Transfer unit motor — toward conveyor |
| `vacuum_gripper` | Q8 | Micro820 | Output | Vacuum valve (picks up workpiece) |
| `workpiece_on_belt` | B1 (I4) | Opta | Input | Light barrier — workpiece deposited on belt |
| `pallet_top` | B2 (I5) | Opta | Input | Light barrier — workpieces on pallet |
| `pallet_ready` | B3 (I7) | Opta | Input | Light barrier — pallet present and empty |
| `slider_home` | S3 (I3) | Opta | Input | Pusher slider in home position |
| `motor_belt` | Q5 | Opta | Output | Conveyor belt motor |
| `separator` | Q6 | Opta | Output | Separator valve (holds workpieces for counting) |
| `pusher` | Q3 | Opta | Output | Motorised pusher (ejects batch onto pallet) |
| `workpiece_count` | — | Opta | SW counter | Running count of workpieces on belt (0–3) |

---

## Repository structure

```
MATRIX/
├── README.md
├── plc/
│   ├── siemens/                  TIA Portal V19 project archive (.ap19)
│   ├── allen-bradley/            CCW project archive (.ccwarchive)
│   └── opta/                     Arduino PLC IDE project (.plcproj)
├── middleware/
│   ├── main.py                   Entry point — starts all three clients and OPC-UA server
│   ├── s7_client.py              S7comm client (python-snap7)
│   ├── ab_client.py              EtherNet/IP + Modbus TCP client (pycomm3 + pymodbus)
│   ├── opta_client.py            Modbus TCP client (pymodbus)
│   ├── opcua_server.py           OPC-UA server (asyncua)
│   └── requirements.txt
├── scada/
│   └── ignition/                 Ignition project export (.gwbk)
├── security/
│   ├── zeek/                     Custom Zeek scripts and policy files
│   ├── snort/                    Custom Snort rules for ICS traffic
│   └── scripts/                  Attack simulation scripts (pymodbus, plcscan wrappers)
├── experiments/
│   ├── baseline/                 Instructions for 24-48 hour baseline capture
│   ├── anomaly-detection/        MATLAB Stateflow IDS model
│   ├── vuln-assessment/          Scan scripts and results templates
│   ├── protocol-comparison/      Latency and overhead measurement scripts
│   └── fault-propagation/        Metasploit resource scripts
└── docs/
    ├── architecture.png          High-resolution architecture diagram
    ├── hmi-mockup.png            Ignition HMI layout reference
    └── fischertechnik/           Fischertechnik model description and wiring tables
```

---

## Publications

Chabeli, K. et al. (2025). *Design and Implementation of MATRIX: A Multi-vendor Heterogeneous ICS/CPS Security Research Testbed*. South African Telecommunication Networks and Applications Conference (SATNAC), 2025. *(Work in progress)*

---

*Intelligent Connectivity Group · Department of Electrical and Computer Engineering · University of Cape Town*
