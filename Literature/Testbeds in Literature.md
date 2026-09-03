# 1. Morris et al.(2011): A control system testbed to validate critical infrastructure Protection Concepts

## 1.1 Paper Summary
This paper describes the creation and application of a multi-industry industrial control system (ICS) and supervisory control and data acquisition (SCADA) cybersecurity testbed developed at Mississippi State University.

To achieve this, the researchers integrated commercial hardware and software—such as programmable logic controllers, human-machine interfaces, and smart grid components—controlling functional physical processes like water storage tanks, gas pipelines, and power transmission systems to discover vulnerabilities, analyze network and software attacks, and evaluate defensive tools such as retrofit data loggers and neural-network-based intrusion detection systems.

The primary **strength** of this testbed lies in its use of real commercial equipment and live physical processes rather than pure software simulations, providing an effective platform for multi-disciplinary student education, workforce development, and practical security validation.

- The control devices include *Remote Terminal Units(RTUs)*, *Programmable Logic Controllers(PLCs).* What is RTU used for (my understanding):
- Physical process include a water storage tank (that models petroleum storage tank), a raised water tower, a factory conveyor belt, a gas pipeline, ans industrial blower, a steel  rolling operations and a smart grid transmission control systems.
## 1.2. Paper's position with existing literature
The author positiion  the testbed against existing testbeds in the literature, citing:
- **Limitations of simulation-based testbeds.** Many academic studies rely purely on software simulation (e.g., MATLAB Simulink, OMNET++, PowerWorld, RINSE, C2WindTunnel). While cost-effective, the authors note that simulated testbeds fail to capture the true, complex interactions of real control system hardware, software stacks, and physical processes.
- **Limitations of National-Scale Facilities:** Large-scale testbeds like the Idaho National Laboratory (INL) SCADA Testbed feature full-scale physical power grids and wireless testbeds. However, INL is dedicated to national enterprise assessments and standards development, and its facilities are **not made available for open-ended university-led research**
- **Differentiation from Other Physical Testbeds:** While other physical testbeds exist (such as Fovino et al.'s turbo-gas power plant model or Hahn et al.'s electric substation model), they focus almost exclusively on electric power generation or transmission.
- **The MSU Niche:** The MSU testbed bridges this gap by providing an **academic-accessible testbed built with commercial off-the-shelf (COTS) hardware and software** spanning a diverse cross-section of critical industries (petrochemical, water, gas, manufacturing, steel, and smart grid transmission). **Furthermore, while most academic research targets routable Ethernet protocols, the MSU testbed explicitly integrates legacy serial-based control systems and wireless industrial radios to study vulnerabilities unique to non-routable infrastructure.**
## 1.3 Experimental Results with the Testbed.
The authors conducted several categories of experiments using testbed to **validate vulnerabilities**, **test retrofit tools**, and **evaluate intrusion detection systems**.
### 1.3.1 Proprietary Industrial Radio Vulnerability Testing

**Methodology:** Researchers tested popular 900 MHz industrial serial radios used to replace null-modem cables. Because proprietary radio specifications and source code were unavailable, physical reverse-engineering and exhaustive laboratory searching were required. Attackers scanned 12,288 network identifier and data rate combinations (~21 to 42 hours) and executed a full parameter search (~39 days) to discover and infiltrate the wireless network.

**Findings:** The radios lack robust authentication to prevent a configured slave from joining an active network. Once infiltrated, attackers can execute eavesdropping, data injection, or complete denial-of-service (DoS) attacks by abusing the carrier-sense back-off mechanism to lock out legitimate traffic.
### 1.3.2 Software HMI Vulnerability Analysis
**Methodology:** Evaluated commercial HMI software packages using chosen-plaintext analysis and code review.

**Findings:** Discovered insecure password storage (passwords obfuscated via simple XOR with a static, recoverable key), insecure remote transmission of credential files over the network, and lack of execution boundaries allowing dynamic link library (DLL) replacement. Replacing the authentication DLL bypassed all checks and granted users elevated privileges (reported to US-CERT as VU#310355)
### 1.3.4 Network Attacks (Command, Response Injection, DoS, and MITM)

**Methodology:** Developed systematic command and response injection attacks against Modbus/DNP3/EtherNet/IP systems, protocol fuzzing/DoS using the MU-4000 Analyzer, and ARP-poisoning Man-in-the-Middle (MITM) attacks using Ettercap

**Findings:** Fuzzing ICMP, ARP, IP, TCP, DNP3, MODBUS, and IEEE C37.118 caused commercial devices to unexpectantly hang or reset. MITM attacks successfully intercepted PMU-to-PDC streams in the smart grid lab, doubling voltage magnitude values before retransmission without proper cryptographic validation.

### 1.3.5 Retrofit Network Data Logger Evaluation

- **Methodology:** Evaluated a "bump-in-the-wire" data logger (built in both a software VM version and a standalone FPGA/Microblaze version) designed to securely log serial MODBUS and DNP3 traffic.
- **Findings:** Confirmed that introducing the data logger added an average latency of **less than 50 ms** (compared to a baseline of ~35 ms), which safely remained well below the 1–2 second RTU polling periods and caused **no harmful side effects** to ongoing control processes. The device successfully stored encrypted, HMAC-signed transaction logs spanning years per gigabyte of storage.

### 1.3.6 Intrusion Detection System (Neural Network) Evaluation
**Methodology:** Tested a three-stage neural network classifier trained via backpropagation on the water storage tank. It used four input features: measured water level, command response frequency, system mode (auto/manual), and pump state. Six classes of false response injection attacks were injected.

**Findings:**
- The neural network successfully detected value-based injection anomalies with high accuracy: **100%** for negative water levels, **95.5%** for HH alarms, **94.7%** for Above-H values, **94.6%** for Below-L values, **96.8%** for LL alarms, and **84.9%** for random values.
- **Major Weakness:** The classifier performed poorly on **replay attacks** (achieving only **12.1% accuracy** with over 40% false positives/negatives) because replayed historical traffic mimics statistically valid operational states.

## 1.4 Strengths and Limitations
### 1.4.1 Strengths
- **Commercial Realism:** Relies entirely on commercial-off-the-shelf (COTS) hardware and software components from multiple vendors rather than purely theoretical models, ensuring realistic device and network stack reactions.
- **Cross-Sector Diversity:** Models multiple critical infrastructure domains (water, gas, manufacturing, steel, and power transmission) within a single research environment.
- **Communication Breadth:** Accommodates both modern routable Ethernet protocols (EtherNet/IP, GOOSE, DNP3/TCP, IEEE C37.118) and legacy non-routable serial networks (MODBUS RTU/ASCII, serial DNP3, proprietary radios).
- **Dual Mission Utility:** Successfully integrates research capabilities with robust academic coursework and workforce development short courses
### 1.4.2 Limitations

- **Scale Constraints:** Significantly smaller in physical scope compared to national-scale enterprise testing facilities like the Idaho National Laboratory testbed.
- **Partial Simulation & Substitution:** Certain physical components are scaled-down or substituted for safety and practicality (e.g., using water instead of oil, and using dummy weights instead of actual steel in the rolling mill).
- **Time-Intensive Attack Discovery:** Certain legacy/proprietary components (such as industrial radio parameter spaces) require extensive manual reverse engineering and lengthy offline search periods (e.g., 39 days) to fully map.

**General Intake**
RTU (Remote Terminal Unit) is a microprocessor-based device used in ICS to connect physical field equipment to a central Supervisory Control and Data Acquisition system(SCADA).It collects sensor data, executes local control logic, and transmits telemetry over long distances via wireless or wired network.

Our testbed does not have RTUs, PLCs are connected to the SCADA layer through the use of a middleware Raspberry Pi. RPi is better than RTU because it has a  real operating system than can run multi-tasks required to different protocol translation between control and physical layer. Basically Raspberry Pi serves the entire purpose of RTU, plus more. This is of course, at a cost of our testbed not being able to capture attack surfaces specific to RTUs.

# 2.  Reaves & Morris (2012): An open virtual testbed for industrial control system security research

## 2.1 Paper Summary

Industrial control system (ICS) and supervisory control and data acquisition (SCADA) security research has historically been hindered by a lack of open, standardized, and repeatable testbeds. Researchers typically rely either on expensive, private laboratory setups or isolated software simulations. These private configurations make third-party validation, result replication, and unbiased evaluation of anomaly-based intrusion detection systems (IDS) nearly impossible

To address these challenges, the authors propose an open, revision-controlled virtual testbed framework built in Python. This framework models discrete industrial control components including virtual remote terminal units, master terminal units, and physical process simulators while remaining lightweight, portable, and accessible to students and researchers without requiring extensive financial backing. Crucially, the virtual testbed is engineered to be interoperable with actual industrial control hardware and capable of generating realistic network and process traffic captures.

To validate the framework, the authors modeled two actual physical systems from the Mississippi State University (MSU) SCADA Security Laboratory: **a water storage tank** and **a gas pipeline**. Their evaluations demonstrated that the virtual testbeds achieved high statistical similarity to physical network traffic, seamlessly integrated with real industrial control devices and wireless serial radios, and exhibited matching vulnerabilities when subjected to simulated cyberattacks.

## 2.2 Testbed and Layers
The virtual testbed framework is broken down into discrete, modular components that communicate via standardized configurations.

**Process Simulator Layer:**
- Simulates and models the mechanics and physical processes (such as fluid dynamics, tank liquid levels, and gas pipeline pressures) using discrete-time Python classes.
- Communicates with virtual devices via a separate UDP/IP back-channel queue, transmitting sensor measurements (inputs) and receiving actuator commands (outputs).

**Virtual Device (VDEV) Layer:**
- Emulates control devices such as Remote Terminal Units (RTUs), Master Terminal Units (MTUs), and Programmable Logic Controllers (PLCs).
- Implemented as standalone processes or within virtual machines, utilizing Python's `modbus-tk` library for application-layer protocol handling and the operating system's network stack for transport and network layers.
- Utilizes abstract objects called **"points"** to provide a protocol-agnostic memory map, allowing control logic to reference variables by name rather than hardcoded memory addresses.
**Communications and Network Layer:**
- Supports MODBUS/TCP over virtual or physical local area networks, and MODBUS/RTU over virtual serial ports or pseudo-terminal pairs.
- Supports integration with real-world ICS hardware, such as Human-Machine Interface (HMI) software packages and proprietary 900 MHz industrial serial radios operating as repeaters.

**Data Logging Layer:**
- Employs standard tools like `tcpdump` for Ethernet traffic capture.
- Introduces a custom utility called **PortLogger** for serial communications, which handles virtual serial port pairing and records transaction logs without altering baseline transmission timing or acting as an intrusive "bump-in-the-wire" device.

So basically this virtual test is the virtualization of the some of the critical infrastructure components of the physical testbeds, presented in the previous reference Morris et al (2011).

# 3. Candell, Zimmerman, & Stouffer (2015): An Industrial Control System Cybersecurity Performance Testbed.

## 3.1 Paper Summary
The paper presents the design of a modular ICS cybersecurity performance testbed whose primary goal is to measure how security protections (drawn from NIST SP 800-82 and ISA/IEC-62443) affect process performance, availability, and resilience. Rather than attempting to replicate an entire plant, the testbed emulates representative industrial scenarios that span slow- and fast-dynamics processes, both continuous and discrete manufacturing, and both IP-routable and non-routable industrial protocols.

Three functional enclaves are described: a **Tennessee Eastman (TE)** chemical-process simulation (continuous, slow dynamics), **a cooperative robotic assembly cell** (discrete, fast dynamics), and **conceptual third enclaves (wide-area SCADA or intelligent transportation)**. Supporting infrastructure includes a dedicated measurement enclave for packet capture, network emulation, and time synchronization, *plus attack platforms for penetration testing* and *traffic manipulation*. The testbed is intended as a shared research platform for *government*, *academia*, and *industry* to evaluate security technologies, generate quantitative performance data, and feed results back into standards development. An extensive appendix supplies performance-metric catalogs, security-requirement mappings, and a detailed simulation case study of network-induced degradation on the TE process.

## 3.1 Testbed Description ( Layered Architecture)
The testbed is organized into independent but interconnected enclaves, each realizing a distinct industrial scenario, plus shared measurement and attack resources.

**Tennessee Eastman (TE) Continuous-Process Enclave**
- **Process layer**: Analog/digital simulation of the classic Downs & Vogel TE plant (reactor, condenser, vapor-liquid separator, stripper, recycle compressor). Produces products G/H from reactants A/C/D/E; open-loop unstable; Mode-1 base case used.
- **Control layer:** Decentralized multi-loop controller (Ricker Simulink design, later ported to C++). Plant and controller run on separate machines; **state exchange via OPC tags.**
- **Network/PLC layer:** Hard-PLC and soft-PLC centers; DeviceNet (non-routable) and EtherNet/IP (routable) via Molex communication cards; shared-memory interface to the process model.
- **Operations & DMZ layers**: HMI for set-point manipulation and visualization; local historian; industrial firewall with deep-packet inspection and device white-listing; enterprise historian in the DMZ.
- **Physical deployment**: Full-height 19-inch rack with UPS, Stratix industrial switches/router, video-management system, and patch-panel links to the measurement enclave.

**Cooperative Robotic Assembly (Discrete, Fast-Dynamics) Enclave**
(This is enclave is very similar to our testbed(24V Production Line))
- **Mechanical/process layer**: Optical table with two KUKA youBot robots, gravity-fed part queue, two machining stations with infrared presence sensors, and custom 3-D-printed spherical end-effectors/receptacles. Parts move clockwise through stations and a robot-to-robot hand-off zone.
- **Safety layer**: Dedicated safety PLC monitoring e-stop button and light curtain; safety relay that de-energizes robot power on fault.
- **Control/software layer**: Robot Operating System (ROS) nodes (Python) for distributed robot control, YouBot EtherCAT driver (SOEM), Modbus interface to the supervisory PLC, and action-plan YAML files. ROS bags enable traffic recording/replay.
- **Network layer**: EtherCAT deterministic real-time protocol between robots and controllers; Layer-3 industrial switch with firewall/VPN capabilities; multiple subnets.
- **Physical deployment**: 42-U rack (PLC, safety PLC, I/O, ROS servers, UPS) plus free-standing optical table and operator HMI station.

**Measurement Enclave**
- Backbone switch/router for the entire lab.
- High-performance multi-NIC server for SPAN-port packet capture (Wireshark/tcpdump).
- Network-emulation server (Ubuntu + netem, MasterShaper, tc, etc.) that can inject delay, jitter, loss, and reordering.
- Ixia traffic generator and Anue appliance for synthetic traffic and man-in-the-middle simulation.
- LANTIME NTP master clock for precise multi-machine timestamping.

**Attack Resources**
- Laptop running Metasploit.
- Ixia M2 for DoS and replay attacks.
- ROS-bag replay capability.
- Traffic-manipulation server (Ixia Anue).

**Third Enclave (Conceptual)**
- Intelligent transportation system (Vanderbilt) or wide-area SCADA (pipeline, rail, water) to complement the two local-area enclaves.

All enclaves share a common measurement backplane and can be reconfigured via industrial switches and patch panels.

## 3.2 Positioning Relative to Existing Literature

The authors situate the work at the intersection of two well-established communities:
- **Process-control research** – the TE problem (Downs & Vogel 1993) and Ricker’s multi-loop controller are canonical benchmarks; the robotic cell extends discrete-manufacturing and ROS-Industrial practice.
- **ICS security guidance** – NIST SP 800-82 and ISA/IEC-62443 (especially 3-3 system requirements and security levels) supply the normative requirements the testbed is designed to validate.

They note that commercial perimeter appliances (Tofino, Cisco ASA, etc.) already implement many of the required security functions, yet lack the instrumentation needed to quantify packet-level performance impact (delay, jitter, loss) on the physical process. Prior academic work on geometric/stealth attacks (Cárdenas et al.) and process-performance assessment (Ordys, Baroudi KPI libraries) is cited as motivation for a measurement-centric testbed rather than another purely defensive or purely simulation platform. The testbed is therefore presented as a bridge that turns qualitative security recommendations into quantitative performance data usable by both standards bodies and plant operators.
## 3.3 Experimental Results
The only concrete experimental campaign reported is the **Tennessee Eastman Simulation Case Study** (Appendix 8.6).
**Method**
- Plant + Ricker controller executed in Simulink (later C++).
- Communication channel between plant and controller modeled as independent two-state Gilbert-Elliot (GE) channels for every measured variable. “Good” state = packet arrives inside the PLC scan window; “bad” state = packet delayed/lost and last known value is held.
- Transition probabilities _P_ (good→bad) and _R_ (bad→good) swept parametrically.
- Twelve single disturbances plus four multi-point disturbance vectors applied under steady-state set-points.
- > 2 000 scenarios executed; full time-series of 41 process variables plus quality and cost indicators recorded.
- Post-processing produced average/maximum/variance of deviation from baseline, correlation to baseline, shutdown indicator, operating-cost metrics, and product-quality (molar % G) metrics. Results stored in an Access database (publicly available via GitHub).
**Key findings**
- Reactor pressure deviation becomes significant once _P_ ≳ 0.1 and _R_ ≲ 0.18; 1-σ of maximum pressure deviation can reach ~25 kPa—material when the plant is operated near the 3 000 kPa shutdown limit.
- Product-quality (molar % G) deviations of 0.6–0.8 % appear across most non-ideal _P_-_R_ regions.
- Operating-cost correlation to baseline remains high provided _R_ ≳ 0.1–0.5; cost itself can actually _decrease_ because of altered material-loss patterns, illustrating that a seemingly favorable economic metric may mask quality degradation.
- The TE process (slow dynamics, ~1 Hz scan) tolerates modest channel congestion if recovery probability is high. Faster processes (robots, safety loops) are expected to be far less tolerant.

No physical-hardware attack or multi-enclave experiments are reported; the paper is primarily a **design and methodology document.** I think we will take this approach for our full paper on Testbed.

The opposite of this would be **'experimental results document** rather than design/methodology paper'.

# 4. Xie et al.(2018): A Virtual Industrial Control System Testbed for Cyber Security Research.

## 4. 1 Paper Summary

The paper introduces VTET (Virtual Tennessee-Eastman Testbed), a primarily virtual ICS testbed designed for laboratory cybersecurity research. It addresses the high cost, risk, space requirements, and recovery difficulty of physical replication testbeds by virtualizing the process and (optionally) the controller while retaining the ability to incorporate a real PLC. The core is the classic Tennessee-Eastman (TE) chemical process simulated in Matlab/Simulink, controlled by either a virtual Siemens PLC (PLCSim + NetToPLCSim) or a physical Siemens PLC. Communication uses three common industrial protocols (OPC, Modbus, and Siemens S7) mediated by an intermediate PC running an OPC server and S7 proxy.

VTET operates in two modes: full-virtualization (everything on PCs) and semi-virtualization (physical PLC replaces the virtual controller). The authors detail the migration of Ricker’s multi-loop TE controller from Simulink into Siemens SCL function blocks running in a cyclic organization block, the network configuration, and the mapping of process variables. To demonstrate utility, they implement and execute five process-targeted attacks that tamper with control logic or sensor/actuator data, showing resulting physical effects such as reactor explosion, productivity loss, and process instability. The testbed is positioned as convenient, low-cost, and suitable for academic research where real damage would be unacceptable.

## 4.2 Testbed Description (Layered)

**Process layer**
- Tennessee-Eastman chemical process (Downs & Vogel) simulated in Matlab/Simulink on PC1.
- Five major units: reactor, condenser, vapor-liquid separator, stripper, recycle compressor.
- Produces products G and H from reactants A, C, D, E (byproduct F).
- 41 measured variables and 12 manipulated variables.
- Nonlinear, continuous, open-loop unstable; controlled under Ricker’s decentralized strategy.
- Process runs cyclically: **generates measurements** → **receives manipulated variables** → **advances to next step**.

**Controller layer**
- **Virtual mode**: Siemens PLCSim (official simulator) + NetToPLCSim (enables network visibility so other components treat it as a real PLC).
- **Semi-virtual mode:** physical Siemens S7 PLC.
- **Controller logic:** 20 control loops originally inside the Simulink TE model are extracted, converted to SCL function blocks via Matlab’s PLC code generation, imported into TIA Portal, mapped to PLC variables, and scheduled in OB35 (100 ms cyclic execution).

**Network / Communication layer**
- **Intermediate PC2 hosts:** – **KEPServerEx OPC server** (variables mapped to process I/O). – Snap7-based S7 proxy that periodically polls the PLC and updates the OPC server.
- PC1 (process) uses Simulink OPC Toolbox and Modbus-Matlab-Simulator to read/write variables over the network, replacing the original internal control loops.
- **Supported protocols:** *OPC*, *Modbus*, *Siemens S7*.
- All components connected via a router; a network sniffer can capture raw TCP/IP traffic.
- In semi-virtual mode, the process can talk directly to the physical PLC via Modbus, bypassing PC2 for some paths.

**Overall architecture (Fig. 1)** Four main elements: PC1 (TE process), PC2 (network mediation), PC3 or physical PLC (controller), and a router. The system is discoverable via network scans, enabling reconnaissance-style experiments. Multi-level data are available: high-level process variables from Matlab and low-level packet captures.

Synthesis: This PC2 intrermediate layer is very similar to my architecture, expecially fro protocol translation (:ggregating different protocols into a unified Middle-ware OPC Server). However, it uses KEPServerEx and a way to switch between physical PLC and PLCSim, and does allow study of **zero-trust micro-segmentation** principle and its effect in system protection. But can I setup this KEPServerEx on my Middle-ware Raspberry pi? Why is RPi a better option than a dedicated PC? welll maybe cost?. what if they used a dedicated Virtual Machine?, a lot cheaper? what would be limitations of that virtualization?,

## 4.3 Experimental Results

The experimental section focuses on demonstrating five process-targeted attacks that are difficult or impossible to run safely on real hardware. Attacks are performed by tampering with the *PLC program (control parameters or logic*) or by *falsifying sensor/actuator data*. Results are shown as time-series plots of key process variables (temperature, pressure, levels, feeds, product f*lows) under normal vs. attacked conditions*.

- **Attack 1 – Exploding the Reactor**: Reduce the integral coefficient of the reactor cooling-water PID by 1.1 %. After ~10 h the reactor temperature and pressure rise sharply; the reactor “explodes” (simulated shutdown/failure).
- **Attack 2 – Reducing Productivity**: Bypass the minimum-productivity constraint and force a 35 % reduction. Feeds of A, C, D, E drop; product flow in the separator declines.
- **Attack 3 – Jamming the Stripper**: Force the separator outlet valve to remain closed when level is below setpoint. Stripper level falls to zero; the controller compensates by increasing reactant feeds; reactor and separator pressures rise until both “explode.”
- **Attack 4 – Increasing the Byproduct**: Reduce A and C inlet valves by 40 %. Products G/H decrease while byproduct F accumulates; stripper level drops, D/E feeds increase, pressures rise, leading to reactor/separator explosion.
- **Attack 5 – Disturbing the Process**: Falsify the stripper-temperature measurement by –20 °C. Cooling water is reduced; actual reactor and separator temperatures and pressures begin to fluctuate; product level and underflow oscillate dramatically, producing instability and lower overall productivity.

The plots (Figs. 9–13) clearly show the divergence from the baseline trajectories and the eventual physical consequences (pressure spikes, level collapses, simulated explosions, or sustained oscillations). The authors conclude that these experiments confirm VTET’s ability to host process-impact attacks that would be unsafe or impractical on a physical plant, making it useful for studying attack effects and developing defenses in a controlled laboratory setting.

No large-scale network attacks, multi-protocol campaign results, or quantitative detection/defense evaluations are reported; the focus is on proving that the virtual/semi-virtual TE + PLC platform can reproduce damaging process-level outcomes.

# 5. Koganti et al. (2017):  A Virtual Testbed for Security Management of Industrial Control Systems.

## 5. 1 Paper Summary
The paper presents the first phase of a fully virtual ICS testbed designed to support security-management research (vulnerability identification, threat assessment, attack simulation, and recovery) on critical infrastructure. Real-world ICS are too large, expensive, and risky for routine experimentation, so the authors build a software-based emulation of a power-grid distribution substation using MATLAB/Simulink for the SCADA/physical process and a Modbus PLC simulator for the controller. The testbed runs on three virtual machines (SCADA, PLC, and attacker) connected on the same network and communicates primarily via Modbus/TCP.

The physical system modeled is the **distribution-breaker setup from the University of Idaho’s** Electrical and Computer Engineering Power Lab (two 3-phase sources, loads, breakers, and Pi-section lines under a load-shedding scheme). The authors demonstrate normal and faulted breaker behavior, implement seven PLC logic conditions that open/trip breakers based on voltage and frequency thresholds, and show two classic cyber attacks: **reconnaissance** (Modbus address scanning) and **denial-of-service (Ettercap)** that succeed against the unauthenticated Modbus/TCP channel. The testbed’s main strengths are fidelity of the Simulink power-system model, ease of modification, and the ability to export high-resolution physical measurements (voltage/current at microsecond resolution) for later security analytics.

## 5.2 Testbed Description (Layered)
**Physical / Process layer**
- Emulation of a power-distribution substation taken from the University of Idaho Power Lab.
- Two 3-phase sources, two loads, voltage/current measurement blocks, three-phase breakers, and three-phase Pi-section transmission lines arranged in a mirrored top/bottom bus configuration.
- Operates under a load-shedding scheme (breakers can be opened to isolate loads).
- Modeled entirely in MATLAB/Simulink using the Simscape Power Systems toolbox.

**SCADA / Monitoring layer**
- Runs on its own Windows 10 virtual machine.
- Reads physical parameters (three-phase voltages and currents) via Simulink “scopes” placed at six points in the circuit.
- Data are exported at microsecond resolution (CSV) for analysis.
- Uses the Instrument Control Toolbox for TCP/IP and Modbus communication.
- Acts as Modbus master: writes measured values into holding/input registers of the PLC and reads control decisions.

**Controller / PLC layer**

- Runs on a second Windows 10 virtual machine.
- Emulated with a Modbus PLC protocol simulator (slave) plus additional Simulink blocks.
- Communicates with SCADA exclusively via Modbus/TCP (port 502).
- Implements seven logic conditions that decide when to open or trip specific breakers based on voltage (< 80 % of nominal) and frequency (< 58 Hz) thresholds, as well as combinations of already-open breakers.
- Stores values in coils/registers; SCADA polls these registers.

**Network / Attack layer**

- All three VMs (SCADA, PLC, attacker) share the same virtual network.
- Primary protocol: Modbus/TCP (no native authentication or encryption).
- Attacker VM runs Kali Linux and can inject packets, perform address scans, or flood the channel (Ettercap used for DoS).
- No additional industrial protocols (e.g., DNP3, IEC 61850) are implemented in this first phase.

**Overall deployment** Three virtual machines only; no physical hardware. The architecture is deliberately simple and extensible so that additional substations, PLCs, or entirely different processes (gas pipeline, water tank, etc.) can be added later.

## 5.3 Experimental Results

The authors first verify correct functional behavior of the emulated plant and controller, then demonstrate two cyber attacks.s

**Functional experiments**
- **Normal (breakers closed)**: Voltage waveforms remain sinusoidal; the sum of the three phase voltages is zero; power is delivered to all loads.
- **Breakers open**: Sudden voltage drop occurs; the waveform ceases to be sinusoidal (illustrated in Figure 5).
- **PLC logic**: Seven explicit conditions are coded (e.g., “if voltage at Breaker 3 < 80 % then open Breaker 7”). When the corresponding thresholds are crossed, the correct breakers open or trip, confirming that the control logic executes as intended.

**Cyber-attack experiments**
- **Reconnaissance (address scan)**: From the Kali VM the attacker sends Modbus “read holding register” requests to random IP addresses. A response containing exception code 04 (server failure) or any valid Modbus reply reveals the presence of a Modbus device and its address (Figure 6). Because Modbus replies even to malformed requests, the scan succeeds and maps the PLC.
- **Denial-of-Service**: **Ettercap** is used on the attacker VM to flood or disrupt the Modbus/TCP channel between SCADA and PLC. Legitimate polling is interrupted, preventing the controller from receiving timely measurements or sending breaker commands.

The paper does not present quantitative metrics (packet-loss rates, detection latency, economic impact, etc.). The experiments serve mainly as proof-of-concept that the virtual testbed can host realistic network-level attacks against an unauthenticated industrial protocol while still generating usable process data. Future work explicitly plans to add man-in-the-middle packet modification, expand the plant model, and apply machine-learning analytics to the exported voltage/current traces for automated detection and self-healing.

# 6. Sicard, Hotellier, & Franq (2022): An Industrial Control System Physical Testbed for Naval Defense Cybersecurity Research

## 6.1 Summary
This paper presents a high-fidelity physical Industrial Control System (ICS) testbed designed specifically for cybersecurity research on **naval defense systems,** particularly warships. The authors highlight the growing cyber risks to Operational Technology (OT) in maritime environments: citing incidents such as NotPetya against Maersk, Ragnar Locker against CMA-CGM, and the potential for catastrophic effects on propulsion, steering, or weapons—while noting that existing ship cybersecurity guidance is limited compared to ports. Real ICS attacks can have severe physical consequences (sabotage, denial of service, safety risks), so safe, realistic platforms are essential for developing and validating defenses.

The testbed implements a scaled but representative model of a surface warship focused on the lower levels of the Purdue model (Levels 0–2). It combines real commercial-off-the-shelf industrial hardware (Siemens and Schneider Electric PLCs, servo drives, HMIs) with a physical ship model that includes rudders, propellers, a fuel tank, and a 76 mm gun turret. Supporting IT elements (virtual machines for trajectory generation, attack generation, and cybersecurity supervision) enable controlled generation of benign navigation scenarios and multiple attack types. Four representative attack scenarios (network intrusion via unknown device, security-invariant violation, offset attacks, and cavitation/oscillation attacks) are described in detail and mapped to the MITRE ATT&CK for ICS framework. The platform supports both knowledge-based and behavior-based intrusion detection research by capturing traffic at multiple points (including fieldbus) and generating datasets. The authors position their work as one of the more advanced physical ICS testbeds for the maritime domain, with future plans for expansion (new components, radio attacks, broader ATT&CK coverage) and use in training and exhibitions.

## 6.2 Full Description of the Testbed
The testbed is a physical ICS platform (with limited virtualization for traffic generation and supervision) structured around the Purdue model, concentrating on Levels 0–2 while adding an IT/MIS overlay (roughly Levels 3–5). It realizes four functional “domain loops” of a warship: **Direction**, **Energy**, **Artillery**, and **Propulsion**—plus coordination and supervisory layers. Real industrial brands (Siemens, Schneider Electric) and protocols are used for fidelity. A physical scale model of a surface frigate provides visible effects of attacks on direction, stability, maneuverability, and artillery.

**Level 0 – Process / Operative Part** Physical actuators and sensors on a ship model:

- **Direction:** two rudders driven by **stepper motors** via Schneider Electric SD328 servo drives.
- **Energy:** **fuel tank with solenoid valves controlled by a peristaltic pum**p via Schneider Electric Altivar ATV61 servo drive.
- **Artillery:** miniature 76 mm gun turret (azimuth, elevation, firing) controlled via all-or-nothing I/O and Profibus to an electronic board.
- **Propulsion:** two steel propellers driven by stepper motors via Siemens G110 servo drives. Fieldbus communications (**Modbus RTU** on Direction and Energy; **Profibus** on Propulsion and Artillery) connect these devices to Level 1.

Note: A servo drive is an electronic device that takes a low-energy command signal from a controller, turn it into a high-power electrical electricity, and sends that power to a servo motor to control its exact speed, position, and torque.

Note: PROFIBUS (Process Field Bus) is a standard digital industrial network used to connect automation controlllers like PLCs, to the factory field devices, such as sensors, actuators and drives. It replaces complex individual wiring with a single purple cable, saving installtion.

**Level 1 – Local Control** Four domain-specific PLCs, each with local HMI and network equipment (switches, industrial firewalls):

- **Direction:** Schneider Electric M340-20.
- **Energy:** Schneider Electric M580-1020.
- **Artillery:** Siemens S7-1214C.
- **Propulsion:** Siemens S7-315. Two coordination PLCs (**Schneider M580-3020** and **Siemens S7-1516**) exchange data among domains and act as gateways (including Modbus/TCP–Profinet) to the supervisory layer. Operators can control domains manually, via local HMI, or remotely.

**Level 2 – Supervisory Control (SCADA)** Siemens Microbox IPC427D industrial PC hosts the central Supervisory Control HMI variables. It consolidates data from the coordination PLCs and domain PLCs, providing a global monitoring and remote-control station. The Supervisory Control HMI displays the overall state of the ship model.
- **IT / MIS overlay (Levels 3–5 equivalent) and supporting infrastructure** Three virtual machines connected via a separate network:
    - **Trajectory Generator VM**: scripts that parse JSON navigation scenarios (rudder angle, duration, speed) and issue commands via **Snap7 (Siemens)** and **PyModbus (Schneider) libraries, simulating normal crew behavior.**
    - **Attack Generator VM:** scripts that launch the four attack scenarios with configurable parameters (**target domain**, whether to fool **Supervisory Control**, **attack vector**).
    - **Cybersecurity Supervision VM:** aggregates logs from sensors for detection and analysis. Network monitoring uses Test Access Points (TAPs):
    - TAPs 1 & 2: commercial OT IDS sensors capturing Ethernet traffic between Levels 2–1.
    - TAP 3: custom RS-485-to-USB probes + Modbus RTU decoder + Zeek IDS for fieldbus traffic between Level 1 and Level 0 (Direction domain). Industrial firewalls and manageable switches provide segmentation and filtering. The overall architecture is shown in the paper’s simplified diagram (ICS network, MIS network, TAPs, and domain loops).

## 6.3 Experimental Results

The paper does not present quantitative experimental results, detection performance metrics, false-positive rates, or large-scale dataset analyses. Instead, it provides detailed qualitative descriptions of four attack scenarios that can be executed on the testbed, together with notes on how they can be detected with the deployed sensors. These serve as proof-of-concept demonstrations of the platform’s utility rather than formal evaluation results.

- **Benign baseline**: Trajectory Generator VM plays JSON-defined navigation sequences (e.g., exit port, maneuvers, return to port). Commands are sent to the relevant PLCs; at the end of a scenario the system returns to idle (rudders centered, propulsion zero).
- **Scenario 1 – Connection of an unknown device (network attack)**: A new node appears on the industrial or fieldbus network and pings existing assets. Detected by OT IDS sensors on the TCP network and by the second RS-485 probe on the fieldbus.
- **Scenario 2 – Violation of a security invariant (process attack)**: Forces the two rudders into opposing positions (illustrated with exaggerated angles). This would mechanically damage a real steering system. Detectable by OT IDS sensors (via tailored rules or behavioral models) and by fieldbus probes.
- **Scenario 3 – Offset attack**: Adds a constant offset (or alters duration) to a command value, violating the intended sequence. Can be launched via corrupted PLC dead-code or direct fieldbus injection. Detection depends on whether Supervisory Control is fooled: without fooling, behavioral models using deep-packet inspection on OT IDS data work; with fooling, only fieldbus probes (present only on Direction) can observe the true process values.
- **Scenario 4 – Cavitation attack**: Injects a configurable-amplitude oscillation around the current setpoint. Detection follows the same network-level and “fool Supervisory Control” logic as Scenario 3.
## 6.4 Critical Synthesis

**Strengths**
- High physical fidelity: real Siemens/Schneider PLCs, servo drives, fieldbuses (Modbus RTU, Profibus), and a tangible ship model produce realistic timing, noise, and physical effects that pure virtual or heavily simulated platforms cannot match.
- Multi-layer coverage and observability: traffic capture from Supervisory Control down to fieldbus (including custom Zeek Modbus RTU support) enables both network- and process-aware detection research.
- Controlled, safe, and repeatable experimentation: Attack and Trajectory Generator VMs allow scripted, parameterized scenarios; the “sandbox” nature avoids damage to real ships.
- Practical relevance: four concrete attack scenarios mapped to MITRE ATT&CK for ICS, support for both knowledge- and behavior-based IDS, and dual use for research, training, and exhibitions.
- Architectural realism within constraints: domain-loop organization, coordination PLCs, and Purdue-aligned layering mirror real naval ICS design more closely than many existing maritime cyber ranges.
**Limitations**

- Incomplete physical coverage: fieldbus monitoring is implemented only on the Direction domain; Propulsion lacks equivalent probes, so certain “fool Supervisory Control” attacks cannot be fully observed there. Artillery and Energy domains receive less attack-scenario attention.
- Scalability and complexity gap: the platform is a simplified, reduced-scale model (far fewer devices and interdependencies than a real warship). Perfect reproduction by third parties is acknowledged as difficult.
- Limited evaluation depth: the paper describes attack capabilities and detection possibilities but provides no quantitative metrics, comparative IDS performance data, or public datasets. Claims of superiority rest largely on architectural description rather than measured results.
- Time and cost constraints inherent to physical testbeds: experiments cannot be accelerated; building and maintaining real hardware is expensive. Radio-frequency (spoofing/jamming) attacks and higher-level IT systems are only planned for future work.
- Restricted attack surface: current scenarios focus on Propulsion and Direction; broader MITRE coverage and more sophisticated multi-stage or lateral-movement campaigns remain future work.

# 7. Mathur & Tippenhauer (2016): A Water Treatment Testbed for Research and Training on ICS Security

## 7.1 Summary
This paper  introduces the Secure Water Treatment (SWaT) testbed, a fully operational, small-scale industrial control system that produces approximately 5 US gallons per hour of filtered water. Designed in collaboration with Singapore’s Public Utilities Board and built by a third-party vendor, SWaT replicates the physical process and control architecture of a modern municipal water-treatment plant within a compact ~90 m² footprint. Its primary purposes are to study the impact of cyber and physical attacks, evaluate attack-detection algorithms, assess defense mechanisms under attack, and examine cascading effects across interdependent ICS.

The testbed implements a six-stage treatment process (raw-water intake, chemical dosing, ultrafiltration, dechlorination, reverse osmosis, and backwash), each controlled by dual **Allen-Bradley PLCs (primary + backup).** Local sensor/actuator communication uses an Ethernet-based Device Level Ring, while inter-PLC and SCADA communication occurs over a Level-1 star network running **EtherNet/IP and CIP.** Both wired and wireless (WPA2) options are available. The authors describe reconnaissance and compromise experiments from three attacker models, concrete process attacks that reduce water output or trigger unnecessary backwash cycles, and lessons learned about layout, protocols, software, sensor placement, and raw-water quality. SWaT is positioned as a realistic, shared research platform intended to help move cyber-security considerations into the design stage of industrial control systems.

## 7.2 Testbed Description:
SWaT follows a classic Purdue-style hierarchical architecture with clear separation of Level 0 (field), Level 1 (local control), and higher supervisory layers.

**Level 0 – Process / Operative Part** Six sequential physical stages (P1–P6) that treat water:
- P1: Raw-water tank (T101), motorized valve MV101, pump P101, level sensor LIT101.
- P2: Chemical dosing station (HCl, NaOCl, NaCl) with static mixer, pumps P201/P203/P205, valves, flow and analytical sensors (FIT201, AIT201–203).
- P3: Ultrafiltration (UF) feed tank (T301), UF feed pump P301, UF membranes, differential-pressure sensor DPIT301, level sensor LIT301.
- P4: RO feed tank (T401), ultraviolet dechlorinator, NaHSO₃ dosing, pump P401, sensors FIT401, AIT402, LIT401.
- P5: Three-stage reverse-osmosis unit, RO boost pump P501, permeate and reject streams, analytical sensors AIT503/AIT504.
- P6: UF backwash tank (T501/T502), backwash pump P602; automatic 30-minute cycle or pressure-triggered cleaning. Sensors measure level, flow, differential pressure, pH, conductivity, ORP, etc. Actuators are pumps, motorized valves, and dosing pumps. Water is recycled within the plant.

**Level 1 – Local / Distributed Control** Six process stages, each governed by a pair of Allen-Bradley ControlLogix PLCs (primary + hot-standby backup).
- **Local fieldbus:** Ethernet-based Device Level Ring (DLR) protocol for sensor ↔ PLC ↔ actuator traffic inside each stage; single-link failure tolerance.
- **Inter-stage communication:** Level-1 Ethernet star network (industrial switch) that interconnects all six PLC pairs, the HMI, SCADA workstation, and historian.
- Protocol stack: EtherNet/IP + Common Industrial Protocol (CIP). Sensor and actuator values are exposed as named “tags” (e.g., MV101, LIT101) that any PLC or SCADA node can read/write.
- Dual-mode communication: every link can be switched between wired Ethernet and industrial Wi-Fi (MOXA AWK-5222, WPA2-PSK).

**Supervisory / Higher Layers (SCADA, HMI, Historian)**
- SCADA system and engineering workstation for global monitoring, set-point changes, and PLC logic download.
- Local HMI (Allen-Bradley PanelView Plus) for operator control of any actuator.
- Historian that records every tag value for offline analysis.
- All supervisory nodes reside on the same Level-1 network (same broadcast domain).

The physical layout places the reverse-osmosis unit in the foreground; tanks, UF unit, and chemical station occupy the remainder of the 90 m² space. Manual switches allow operators or researchers to reconfigure wired versus wireless paths on demand.

## 7.3 Experimental Results
The paper reports qualitative and semi-quantitative results from reconnaissance, compromise, and process-manipulation experiments rather than large-scale statistical evaluations of detection algorithms.

- **Attacker models & reconnaissance** Three models were considered:
    - A – network access on the Level-1 LAN,
    - B – wireless proximity,
    - C – physical access to devices. 
- Using standard tools (Wireshark, Zenmap, Ettercap) the authors mapped the network, discovered web interfaces, anonymous FTP on the HMI, and the absence of authentication/encryption on EtherNet/IP. ARP spoofing succeeded, enabling full man-in-the-middle interception and rewriting of tags. Wireless reconnaissance revealed a weak, dictionary-guessable WPA2 pre-shared key and a default administrative password on the access point that exposed the key in clear text. Physical access experiments identified SD-card slots on the PLCs as a potential logic-update vector.
- Thier findings is that ENIP, does not feature any authentication or encryption in out testbed.(It could easily be decoded using protocol analysers such as wireshark). The author also note that they are currently working on `scapy` tool which will aid in generation of ENIP traffic.
- Thier reconnaissance also revealed that its was possible to capture actions such as remote firmware and logic updates from SCADA to individual PLCs ( And attacker could have access to the program logic or able to manipulate the logic)
- **Process attacks and system respons e**
    - Attack on differential-pressure sensor DPIT301: the reported value was raised from 20 kPa to 42 kPa. PLC-3 immediately initiated an unscheduled UF backwash cycle.
    - Attack on level sensor LIT401: the reported RO-feed-tank level was lowered from 800 mm to 200 mm. PLC-5 stopped pump P401, reducing treated-water output from an expected 155 gallons to 113 gallons in the observation window (nominal production ≈ 5 gal min⁻¹).
    - Additional experiments examined physics-based (process-invariant) detectors. Key findings include: – the number of consecutive sensor samples used by both the control logic and the detector strongly affects detection latency and false-alarm rate; – intermittent (pulse-width-modulated) attacks can evade simple invariant checks; – attacks launched immediately before or after a power outage are especially hard for invariant-based methods to detect.

No formal detection-rate tables or ROC curves are presented; the emphasis is on demonstrating realistic attack impact and identifying design parameters that influence detector performance.

Note: You can revisit the experiments, if you want to clone them in your code.

## 7. 4 Analysis
**Strengths**
- High operational fidelity: real water is treated through a multi-stage process whose hydraulics, chemistry, and control logic closely match municipal plants, thanks to collaboration with the national water utility.
- Realistic industrial hardware and protocols (**Allen-Bradley ControlLogix,** EtherNet/IP/CIP, Device Level Ring, dual PLCs) provide authentic timing, noise, and failure modes that pure simulators lack.
- Flexible communication (wired/wireless switchable) and dual-PLC redundancy enable a wide range of network- and physical-attack scenarios.
- Shared research platform: the facility is explicitly open to external collaborators, supporting the broader goal of embedding security into ICS design.
- Concrete attack demonstrations (tank overflow, forced backwash, production degradation) give researchers tangible, reproducible effects against which detectors can be evaluated.

**Limitations**
- **Incomplete instrumentation:** several stages lack sensors that would be useful for system identification or quality-attack studies (e.g., no pH sensor immediately after the UF unit).
- **Data-extraction friction:** the commercial historian requires manual per-tag export; automated retrieval is cumbersome.
- **Protocol tooling:** EtherNet/IP has far less open-source support than Modbus/TCP, forcing researchers to extend tools such as Scapy.
- Physical layout: the compact arrangement is poorly suited to groups larger than five visitors and offers limited physical separation for safety barriers.
- Water quality constraint: the plant is designed for relatively clean campus water; introducing realistic “raw” water risks damaging membranes and dosing systems.
- Scale and dynamics: tank volumes are large enough that attack effects (e.g., overflow) take many minutes to become visible, slowing experimental iteration compared with smaller bench-top setups.
- Evaluation depth: the paper focuses on attack feasibility and qualitative lessons rather than rigorous, quantitative comparisons of detection or defense algorithms.

In summary, SWaT is one of the most realistic and accessible water-treatment ICS testbeds available for security research. Its main value lies in the authenticity of the physical process and industrial control stack; its principal shortcomings are incomplete sensor coverage, proprietary software interfaces, and the absence of large-scale quantitative detection studies within the paper itself.

## 7. 5 Synthesis
SWaT is deliberately homogeneous: all process stages use Allen-Bradley/Rockwell ControlLogix PLCs and the EtherNet/IP + CIP stack (with Device Level Ring at Level 0). This design choice simplifies experimentation and guarantees clean, reproducible results, but it also limits the range of research questions the testbed can answer. Introducing controllers from multiple vendors (e.g., Siemens, Schneider Electric, Rockwell, ABB, Mitsubishi) together with heterogeneous protocols (Modbus/TCP, Profinet, EtherNet/IP, OPC-UA, BACnet, etc.) would unlock a significantly richer set of research questions that more closely match real-world ICS deployments.

The following are typical critical research questions that a homogeneous testbed can not address:
- How do protocol gateways and converters themselves become attack surfaces?
- Can an attacker exploit semantic mismatches or incomplete translation between protocols (e.g., Modbus register vs. CIP tag vs. Profinet I/O) to inject false data that remains undetectable by either side?
- What are the security properties of commercial multi-protocol gateways under active attack?
- Can a compromise of one vendor’s PLC be used to pivot into another vendor’s control domain?
- How do differences in authentication, session handling, and firmware update mechanisms across vendors affect the feasibility and stealth of multi-stage attacks?
- What cascading physical effects occur when an attack crosses a protocol/vendor boundary?

# 8. Kraust, Heller, & Mottok (2025): Concept for Designing an ICS Testbed from a Penetration Testing Perspective

## 8.1 Overall Summary of the Paper

This paper proposes an iterative, adversary-centric (penetration-testing-oriented) concept for designing Industrial Control System (ICS) cybersecurity testbeds. The authors argue that most existing ICS testbeds are built from a defender’s or process-fidelity perspective: they replicate real or reference industrial processes (often with high physical fidelity), which makes them expensive, difficult to reconfigure, poorly scalable, and ill-suited to systematically exploring attack chaining, configuration variants, software/version diversity, and lateral movement across security boundaries. In contrast, the authors advocate a bottom-up, modular approach that begins with a minimal viable setup and incrementally expands complexity only after each layer has been thoroughly tested.

The core contribution is a two-stage process (Static System Model definition followed by a Dynamic Penetration Testing Cycle). A Static System Model (SSM) captures the full architecture, devices, communication relationships, services, and external entry points. From this, a restricted System View Model (SVM) is extracted—the portion initially visible/accessible to an adversary. Security boundaries are defined by the perimeter of the SVM; successfully crossing them constitutes a successful breach. Within each testing cycle the attacker’s placement, initial access vectors, and system configurations (including selected vulnerabilities and misconfigurations) can be varied. Impact is assessed primarily via lateral movement beyond the SVM or degradation of operational status. The process draws on the MITRE ATT&CK framework (Enterprise and ICS matrices) to systematize prerequisites, goal indicators, tool enumeration, interactions, and knowledge updates. After sufficient testing of a given model, the SSM or SVM can be refined or expanded, enabling progressive exploration of defense-in-depth and complex attack chains while keeping each iteration manageable.

A secondary contribution is a structured literature analysis of representative ICS testbeds (SWaT, RICS-el, Lancaster, Maynard et al., Hui et al., NIST, VTET, etc.). Using metrics such as category (physical/virtual/hybrid), cost, protocols, coverage of Purdue-model zones (Manufacturing, DMZ, Enterprise), and whether a design derivation process is described, the authors highlight recurring shortcomings: sparse attention to design methodology, over-representation of a few protocols (especially Modbus), limited modeling of IT–OT transitions and modern protocols such as OPC UA, process-centric rather than network/attack-chain focus, and poor reproducibility/scalability of high-fidelity physical setups. The paper concludes by positioning the proposed concept as a remedy and stating the intention to realize a proof-of-concept OPC UA testbed (to be open-sourced) for generating training data for AI-based intrusion detection and automated penetration-testing agents.

No concrete testbed is implemented or described in operational detail in this paper; the work is a conceptual and methodological proposal. An illustrative network architecture is shown in Figure 1, covering multiple levels of the automation hierarchy (Purdue model / IEC 62443). It comprises:

- An OT/Manufacturing Zone with generic control devices on the lower levels.
- An IT/Enterprise Zone with enterprise systems on the upper levels.
- Intermediate elements consistent with a typical DMZ separation (though not exhaustively detailed).

The figure marks an “exposed system view model” (red dashed frame) that represents the portion initially visible to an adversary, with one possible entry point highlighted. The full network constitutes the Static System Model; the dashed subset is the System View Model. No specific device inventory, exact inter-device protocols, IP addressing, or concrete software versions are given for this illustrative model—precisely because the concept deliberately leaves configurations variable and to be fixed only inside each Dynamic Penetration Testing Cycle.

The authors explicitly state that future work will apply the concept to construct an OPC UA-centric testbed. OPC UA is highlighted because it is underrepresented in existing literature (relative to **Modbus**, **DNP3**, **EtherNet/IP**, **s7comm**, etc.), supports modern service-oriented interactions (discovery, authentication, etc.), and is increasingly important in industrial systems. The planned testbed is intended to be modular (favoring containerization for easy swapping of components and hybrid operation), network-oriented rather than process-oriented, and open-sourced. No further architectural layers, protocol mappings between specific devices, or implementation details are provided in the present document.

# 9. Jorge et al(2025): Containerized Testbed Architecture for Cybersecurity Data Collection on Malicious Activities in Industrial Water Systems

## 9.1 Overall Paper Summary
This paper presents a fully containerized, open-source testbed architecture for cybersecurity research on industrial water systems (capture, treatment, and distribution). Motivated by the increasing IT/OT convergence under Industry 4.0, the scarcity of up-to-date public datasets, and the high cost/limited accessibility of physical testbeds (e.g., SWaT, WADI), the authors design a modular Docker-based platform structured according to the Purdue Enterprise Reference Architecture (PERA). The testbed simulates realistic device behavior, network traffic, and process dynamics while enabling controlled cyberattack scenarios and centralized multi-source data collection (network packets, logs, and resource metrics) via the ELK stack.

The architecture integrates traditional ICS components (PLCs, SCADA) with Industry 4.0 elements (IoT devices, MQTT, HTTP/REST). Three subprocesses (SP1–SP3) cover the full water cycle, using Modbus TCP for PLC control, MQTT for intermediate distribution, and HTTP for digital metering. An attacker container (Kali Linux) performs reconnaissance (Nmap), DDoS (hping3), web-service scanning (Nikto), and Modbus command-injection attacks. Experiments demonstrate successful simulation of normal operation and malicious activities, with clear observable impacts on metrics and the ability to collect labeled data suitable for machine-learning-based detection research. The platform is released on GitHub and is positioned as a low-cost, reproducible, and scalable alternative to physical or complex virtual testbeds.

## 9.2 Testbed Architecture

The testbed is a pure virtual, containerized (Docker + Docker Compose) environment running on a Linux host. It follows the Purdue model and is segmented into three Docker networks:
- **scadanet** (172.20.0.0/16) – ICS core
- **cloud** (172.19.0.0/16) – IoT / distribution / data services
- **elk** (172.21.0.0/16) – monitoring and data collection

**Layer / Purdue mapping and components**
- **Level 0 (Process)** – Simulated via software functions that generate realistic, time-correlated random values for sensors and actuators (dam level, tank level, network pressure, flow, pump status). No physical hardware.
- **Level 1 (Control)**
    - Three independent PLC containers (Python + pyModbusTCP.server):  
        – PLC1: dam level (register 0)  
        – PLC2: treatment-tank level + capture-pump control (registers 0/1)  
        – PLC3: network pressure + distribution-pump/pressurizer control (registers 0/1)
    - Protocol: **Modbus TCP** (port 502).
- **Level 2 (Supervisory)**
    - SCADAPY (lightweight Python Modbus client + REST API)
    - SCADABR (full open-source SCADA, supports multiple protocols, HMI, historian-like functionality)
    - Protocols used to pull data: **Modbus TCP**, **MQTT**, **HTTP**.
- **Level 3 / Industrial perimeter & Level 4 / Business** (simplified)
    - MQTT broker (Eclipse Mosquitto) + MQTT Sensor / MQTT Actuator containers (Java) for intermediate distribution (SP2).
    - Digital water-meter container (shell script) + RESTful web service (Spring Boot + H2 database) for final distribution metering (SP3).
    - Protocols: **MQTT** (topic sensor/pressure or similar, port 1883) and **HTTP/REST** (JSON POST/GET, port 8080).

**Process flow (three subprocesses)**
- **SP1 (Capture & Treatment)**: PLC1–PLC3 + sensors/actuators over Modbus TCP.
- **SP2 (Intermediate Distribution)**: IoT pressure sensor publishes → MQTT broker → IoT actuator (pressurizer) subscribes and acts.
- **SP3 (Final Distribution / Metering)**: Digital meter sends flow readings via HTTP POST to REST service for storage/billing simulation.

All operational data converge in the SCADA systems, which present a consolidated HMI view. An attacker container is attached to both scadanet and cloud networks and can reach every component. Data collection (Packetbeat, Filebeat, Metricbeat → Logstash → Elasticsearch → Kibana) runs on the elk network and captures traffic, container logs, and host/container resource metrics.

## 9.3 Experiments

Experiments were conducted in two phases: normal operation and attack scenarios.
**Normal operation**
- PLCs continuously update Modbus registers with realistic random walks.
- MQTT sensor publishes pressure values every 30 s; actuator reacts according to thresholds.
- Digital meter periodically POSTs JSON flow readings.
- SCADABR successfully registers all data sources and displays live values, historical trends, and a graphical process overview (reservoirs, pumps, sensors).

**Attack scenarios** (MITRE ATT&CK for ICS inspired)
1. **Reconnaissance**: Nmap host discovery (-sn) and service/version detection (-sV -O) correctly identified open ports 502 (Modbus) and 1883 (MQTT) and the associated services. Packet captures showed the scanning traffic.
2. **DDoS (SYN flood)**: hping3 with random source IPs against PLC3 (port 502). Results:
    - ~300 % increase in network traffic.
    - Clear spikes in CPU and memory utilization of the target container (visualized in Kibana).
    - External (randomized) source IPs appeared in Packetbeat captures.
3. **Web-service attack**: Nikto scans against SCADAPY, SCADABR, and the REST service revealed missing security headers (X-Frame-Options, X-XSS-Protection, etc.), enabled PUT/DELETE methods on SCADABR, and exposure of Tomcat manager interfaces—classic misconfigurations that enable XSS, clickjacking, data injection, or application deployment.
4. **Modbus command injection**: Custom Python script (pymodbus) successfully wrote the value 100 into register 0 of all three PLCs, altering the reported dam level, tank level, and network pressure. Packet captures confirmed the write requests from the attacker IP.

All attack traffic, logs, and metric changes were successfully ingested by the ELK stack, demonstrating the platform’s suitability for generating labeled datasets for detection research. The authors emphasize that the attacks served primarily to validate data-collection capabilities rather than to perform exhaustive vulnerability research.

**Strengths*
- **Accessibility and reproducibility**: Fully open-source (GitHub), pure Docker, no proprietary hardware or licenses. Any researcher can stand up the entire environment with Docker Compose.
- **Modularity and Industry 4.0 coverage**: Clean separation of traditional ICS (Modbus PLCs + SCADA) and modern IoT components (MQTT, HTTP/REST). Easy to swap or extend containers.
- **Realistic data collection**: Multi-source (packets + logs + metrics) via a production-grade stack (ELK). Enables both network-based and host-based detection research.
- **Purdue-aligned segmentation**: Clear network isolation supports realistic lateral-movement and zone-traversal studies.
- **Low cost and rapid iteration**: Ideal for generating large volumes of attack data or teaching environments.

**Limitations**

- **Fidelity of process simulation**: Sensor/actuator values are simple random walks with basic threshold logic; there is no fluid-dynamics, chemistry, or closed-loop control model. Physical-process attacks (e.g., altering chemical dosing as in the Oldsmar incident) cannot be studied with realistic consequences.
- **Limited protocol and device diversity**: Only Modbus TCP, MQTT, and HTTP. No OPC UA, DNP3, EtherNet/IP, PROFINET, or proprietary PLC firmware.
- **Simplified IT/OT boundary**: No true DMZ, enterprise-zone services, or realistic authentication/authorization between zones.
- **Attack surface is artificial**: Many vulnerabilities (open Tomcat managers, missing headers, unauthenticated Modbus) are configuration artifacts of the simulation rather than inherent protocol or product weaknesses.
- **Scalability and performance claims unquantified**: No large-scale experiments, multi-tenant use, or resource-consumption benchmarks under sustained load.
- **No defensive components**: Firewalls, IDS/IPS, or SIEM correlation rules are left for future work; the current platform is primarily an attack-and-collect environment.

# Shore, Zeadally, Keshaariya(2021): Zero Trust: The What,How, Why, and When

(This is not a testbed paper, its a paper on Zero Trust, I just need to understand it)
### 1. What is Zero Trust?

Zero Trust is a **data-centric security paradigm** based on the principle  
**“Never trust, always verify.”**
It rests on two fundamental assumptions:
- External **and internal** threats are always present on the network.
- Being “inside” the network (local/internal) does **not** make anything trusted. Lateral movement by attackers is a proven and common tactic.
**Core concepts commonly associated with Zero Trust:**
- **Just-in-Time Access (JITA)** + **Just-Enough Access (JEA)**: Authentication and authorization decisions are made at the moment of the request; only the minimum privileges needed for that specific request are granted, and only for the duration of the request.
- Tokenization or encryption of sensitive data to shrink the attack surface.
- **Adaptive / dynamic policies** that continuously recompute access decisions using as many contextual signals as possible (identity, device posture, location, time, threat intelligence, behavior, etc.).
Zero Trust does **not** eliminate the need for assurance of the underlying security mechanisms themselves. It simply removes the assumption of ongoing trust after an initial check and forces continuous re-evaluation.

The authors note that there is still no single universally agreed definition, but the above ideas form the practical core.

### 2. How is Zero Trust Architected?

**NIST SP 800-207 (2020)** is the primary reference. It defines seven original tenets and a logical architecture with three zones:
- **Untrusted Zone** (users, devices, external networks)
- **Policy Domain** (the decision-making core)
    - Policy Engine + Policy Administrator = **Policy Decision Point (PDP)**
    - **Policy Enforcement Point (PEP)** that actually grants or denies access
- **Implicit Trusted Zone** (the protected resources)
Access decisions are made dynamically using risk-based policies and a trust algorithm. Supporting components include PKI, threat intelligence feeds, continuous diagnostics & mitigation, logging/SIEM, etc.

**Other frameworks mentioned:**
- Forrester’s Zero Trust Extended (ZTX) ecosystem (broader data flows across cloud, IoT, endpoints).
- Gartner’s Continuous Adaptive Risk and Trust Assessment (CARTA).

**Authors’ Enhanced Model (Figure 3)**  
They extend the NIST model by explicitly incorporating:
- Subject situation **and** endpoint situation.
- An **Environment Monitor** that maintains rich situational awareness (device posture, threat intel, traffic patterns, etc.).
- An Intrusion Detection/Filter gateway on the data path.
- Clear mapping of their extended tenets onto the architecture.
They also emphasize micro-segmentation of all objects and end-to-end securing of communications.

### 3. Why is Zero Trust Needed / Implemented?

Traditional perimeter-based security (“castle-and-moat”) and evaluation schemes (TCSEC, ITSEC, Common Criteria) have failed to deliver adequate confidence in modern, dynamic, highly interconnected environments.
**Key drivers:*
- Digital transformation, cloud, mobile workforce, and IoT have dissolved the traditional network perimeter.
- Attackers routinely gain an initial foothold and then move laterally.
- High-profile incidents (e.g., the 2010 Akamai attack) showed the need to separate application access from network access and limit the blast radius of any compromise.
- Legacy trust models assume that “inside = trusted,” which is no longer valid.

**Claimed benefits** (from Microsoft, Forescout, and others cited in the paper):
- Better adaptation to complexity and mobility.
- Improved visibility.
- Reduced infrastructure cost and compliance effort.
- Support for digital transformation.
- Ability to secure unmanaged or constrained devices.
- Dramatically reduced opportunity for lateral movement.

### 4. When to Switch to Zero Trust?

The paper discusses practical triggers and implementation guidance:
**Common triggers:**
- A major intrusion or security incident.
- Replacement of network equipment that already supports Zero Trust features.
- Business changes that expand the attack surface — especially large-scale remote/hybrid work, cloud adoption, or increased third-party access.

**Implementation advice (drawing on Francis and others):**
1. Clearly define the scope of the Zero Trust deployment.
2. Inventory data assets, users, and physical/IT assets in scope.
3. Map all data flows (client-to-server and server-to-server).
4. Define fine-grained access policies.
5. Micro-segment the network and place Policy Enforcement Points appropriately.
6. Start with the most critical assets and expand iteratively.

Several large organizations (Google BeyondCorp, Palo Alto Networks, GitLab, Akamai itself) have already adopted Zero Trust at scale, demonstrating that it is mature enough for production use