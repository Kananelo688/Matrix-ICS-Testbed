
# 1. NOORIZADEH et al (2021): A Cyber-Security Methodology for a Cyber-Physical Industrial Control System Testbed

## Overview
The paper presents investigates and proposes implementation of ICS testbed where Tennessee Eastman process is simulated in a real-time on a PC and the closed loop controllers are implemented on Siemens PLCs. They inject cyber attack through man-in-the-middle structure where the malicious hacker can in real-time modify the sensor measurements that are sent to PLCs.


**Synthesis:** Only read abstract only, but do they use only PLCs? meaning no multi-vendor, multi-propocol invesitigative research are possible in tthier testbed. also whats Tennesse Eastman proceess? My sources are telling me that TEP is a simulated open-source industrial chemical process designed by the Eastman Chemical Company in 1993. It serves as realistic benchmarking in engineering for testing, validating,  and comparing proceess control designs, fault detection algorithms, and machine-learning based anomaly detection methods.


## Testbed Structure
The ICS testbed presented here is hybrid and comprise of three main components: physical plant, embedded system for implementing the controller, and communication network.

The plant is simulated inside a PC, the controller is implemented on actual PLC, and communcation is established by using PROFINET ( standard used by Seimen's PLCs). THe testbed is partitioned into four layers: 
- Tennesse Eastman Plant: this is implemented on a PC (simulated on a PC)
- Field Devices that are emulated by using DAQ and Seimens distributed I/O
- Control layer implementetion using Seimens PLCs.
- The supervisory layer using additional Seimens PLC and a web-server. 
Maths model of TEP is implemented in simulink environment and controllers are implemented using PLCs.Interface between plant simulation and PLCs is accomplished by using DAQ boards and distributed I/O modules. The DAQ boards and distribted I/O modules emulate the layer 1. field layer.  wait! isn't layer 1 supposed to be control devices? , and layer 0 be the field devices? LIttle confused by thier mapping of testbed against industrial automation architecture(Purdue Model)

The supervitory layer consists of a PLC 6 and database.

Synthesis: In actual industrial systems, do PLCs ever work on supervitory layer? and what are limitations? there are lot of open source tSCADA systems that could have been used. Again. what are limitations of using PLC as SCADA layer?

In there PLC-PLC communication? paper didn't explicitly state this. Several PLCs control the large plant but not sharing communication. How is control logic actually implemented.

# 2. Candell, Zimmerman, & Stouffer (2015): An Industrial Control System Cybersecurity Performance Testbed



## Overview
The NIST is developing cybersecuroity testbed performance testbed for ICS. The goal of the this testbed  is to measure the performance of on ICS when instrumented with cybersecurity protections in accordance with the best practises and requirements prescribed by national and international standards and guidelines.

The testbed also several industrial scenarios. First is implements the TE process, as did by Noorizadeh et al. TE is well known control systems problem in chemical process. The authors argue that very ideal for cybersecurity research ebcause its open-loop unstable process and requires closed-loop control to maitain process stability and optimize operational costs.

The second is a robotic assembly system where industrial robots work together cooporatively to accomplish the task of moving parts through simulated manufacturing operatoion. ( This is very similar to our Fischertechnik system used in our research ICS testbed.)

The third will be designed  by Vanderbilt University under a cooporative research aggrement woith NIST. Several concepts were proposed for the third enclave includinggg pipeline network woith a WAN SCADA infrustructure (This is a big win for this testbed, a distributed SCADA.)

Important point from the paper worth noting:
Various commercial products such as CISCO Adaptive Security Appliance firewall devices provide feature-rich security capabilities. However these devices do not provide the ability to measure network performance a function of packet flight metrics: delay, jitter, noise, and so on.

## Testbed Description
### Tennessee Eastman Process
Authors choose TEP as continous process model. Why?
- well known control system, and its dynamics are well understood.
- The plant simulator is implemented is software as in previous reviewed paper. They have both soft and hard PLCs ( diversity is good, but how useful is such), they have historians, HMIs.
The TE communication interface between PLC and plant simulator PC is through EtherNet/IP. THE PLC sends and recieves actuator commands using OPC. ( This kind protocol setup that I am having for my testbed. Worth noting is progress paper).

The system works by continously pooling  the process states( sensor readings) from the communication bus/network, and updates the corresponding OPC tags for use by the controller process. The actuator commands resulting from the controller process are recieved by PLC via scanning OPC tags, ansd the states propagate back dwon through the architecture to emulated actuator devices.

The comm between simulink controller and industrial network is done via OPC. ( not OPC UA, cause apprently they are different, paper is not saying "OPC UA", ?). On every control iteration, the controller pulls the current plantr simulattion states from the OPC server and returns the controller states( actuator commands) to the OPC server used by the plant model.e

Synthesis: This continuous pooling is very problematic as it send huge packets over the network unnecessarily. Also, they multi-protocol architecture is good for divrsity. How ever mult-vendor not supported. Authors didn't specify what PLC they used, by from comm protocol used, I can deduce its Allen-Bradley PLCs. My test bed offer multi-vendor and multi-protocol, beats this one by large margin. Need to stretch this limitation is our progress paper.

### Cooporate Robotic Assembly for Smart Manufacturing( Closest to pur fischer technink plant we use in our testbed)

the controll layer is composed of nodes (ROS Nodes) that control the robots.
It then features Modbus interface for allowing any ROS node to monitor sensors, operator buttons, and states from the PLC.

The PLC I/O layer serves as the bridge between ROS and PLC. the PLC Contains supervitory contorlm software of the ecnlave, which ROS nodes monitor through the Modbus interface. HMI will serve as a graphical representation of the current states of the robots, and the contol system.  It was developed in Python. The GUI will include controls, such as program start and stop, system state indicators, safety indicators,and program selection.

# 3.Xie et al (2018)VTET: A Virtual Industrial Control System Testbed for Cyber Security Research

## Overview 
The paper presents VTET, a virtual ICS testbed  for cyber-security research. VTET contains virtual chemical industrial process, and both virtual and physical controllers.

The  testbed comprise of 4 main components: a physical PLC,  a PC used for network communicartion, and two PCs simulating the process and PLC respectively.

## Testbed Architecture and Procols
PC1 is simulating the TE process( again, seems to be quite commonly simulated process this one). The testbed supports OPC, S7, and Modbus communication protocols. It can work in both fully-virtualized mode only or hybrid. PC2 is for network comms. It host OPC server, and S7 proxy. ( Its kinda same to be Raspberry Pi middleware I am planning to use for my testbed). PC2 si simulating the PLC (PLCSim and NetToPLCSim), and then Physical PLC that connects directly to PC1 (TE process) via Modbus.

PC1 generates measurements of the process and sends them to PC2 via OPC. PC3 or Physical PLC queries the OPC server or S7 proxy in PC2 for measurements and generates the manipulated variables, then send them back to PC2. Process in PC1 queries these, and updates its state.

The virtualization of PLC is implemented using PLCSim and NetToplcsIM. PLC is official simulator of Seimens PLCs. it could simulate most functions of the real PLC, but can't communicate with other components throught he network. They then introduced NetToPLCSIm to enable the network comm of PLCSIm. With this NetToPLCSim, other ICS components(HMI, SCADA which authors do not provide details if theyb implemented they or  not) would see PLCSim as real physical PLC.

Synthesis: What is significance of physical PLC in this if no actual I/O ports are used. all readings and actuator commands seem to be in virtual form. This is very different form Noorizadeh's testbed of for the same process who actually had DAQ to interface simulink implementation on TE with the actual PLC I/O modules. The testbed also doesn't show clearly specificaly what Purdue  model layers have been implemented, and which have not been implemented. 

# 4.  Alves, Das & Morris (2016) - Virtualization of Industrial Control System Testbeds for Cybersecurity

## Overview
The paper examines the fedility of a virtual SCADA Testbed to a physical testbed and allows for the study of the effects on both of the systems.


The goal of their paper is to create two testbeds- one physical and one virtual where the  virtual is the model of the physical.

The author presents the Gas Pipeline Testbed which is a small closed pipeline that tries to mimic the behavior of a real gas pipeline. The pump, actuators, and solenoids are connected to the PLC that controls the system. PLC simply maintains the pressure between a high and a low setpoint by turning on and off the pump. The user can also control the pressure via HMI.

Any SCADA is divided into physical system, wire bridge, PLC, Scada protocol,and HMI. It possible to virtualize each part and compare its fedility to the physicals segment.

The virtual  counter part of the system was modelled in Simulink Matlab.

wire bridge between physical system and PLC was modeled as UDP packets that act as virtual wires of the system. A program was written in order to capture the data from Matlab model and send them to the PLC. A virtual I/O driver was writtenn for the PLC to interpret these packets as if they were local I/O.

The authors used ModbusTCP as the protocol for Gas pipeline Testbed. 

The HMI was created in C# and Uses EasyModbusTCP library to communicate with OpenPLC over Modubus TCP. 

They used OpenPLC to virtualize the Physical PLC, running on UniPi.

Synthesis: This s very simple testbed. The goal is to validate the fedility of virtual testbed to a physical one. They result showed that the virtual testbed, when developed to closely model real physical testbeds can provide necessary fedility with the physical testbed. that really. How does this compare to others? well, it a very simple testbed, single PLC controlling pressure in a pipe. Uses single protocol: Modubus TCP, and lack diversity. the system has being build upto layer 2( actual SCADA system). The gaps that by testbed tries to fill and very evident here.

# 5. Koganti et al (2017): A Virtual Testbed for Security Management of Industrial Control Systems

## Overview
The paper describes the first phase of implementing of a virtual testbed for power grid distribution using MATLAB Simulink and PLC Simulator.

The virtual testbed consists of two subsystems: SCADA Subsystem emulated over MATLAB  Simulinka and PLC subsystem emulated using Modbus PLC protocol simulator and MATLAB Simulink. There are 3 virtual machines. firsy simulates SCADA subsystem, second is PLC and third attacker Vitual Machine. All the three VMs need to be on the same network.

Virtual testbed. Nothing interestoing to source from this paper.

# 6.  Azimi, Sami, & Khalili - A Security Test-Bed for Industrial Control Systems
- The authors propose industrial testbed for evaluating the security of industrial applications by providing different metrics for static testing, dynamic testing, and network testing in industrial settings.
- In legacy ICS, remote access was not required which resulted in systems designed and developed without security considerations. Recently, however, the industrial devices are getting smatter and smarter, as they got integrated ICT systems with ICS. An example would be using ICT network to remotely control the ICS-layer 1 device such as PLC.
- This integration resulted in dangeros vulnerabilities and attack surfeces for indurstrial control systems.
- The priority of vulnerabilities in ICTs and ICS are different becaase theier security objective are different in the first place:
	- In ICT, information **confidentiality** hold highest priority, followed by **integrity**, and **availability** at lowest priority ( CIA).
	- In ICS, the order is exavt reverse. ICS give availability the highest priority because information availability is vital for monitoring and controlling processes.( temperature sensor reading is much more important for plat control than its confidentiality or integrity.)
- Authors mention that industrial tests mainly consists of three tests:
	- **static tests:** This uses world-wide standards to to extract security, performance, and maintainance bugs by analyzng the source code.
	- **dynamic tests:** These tests do not consider the source code, but run the program to detect security bugs and issues. 
	- **Network Test**: This deals with ICS network test which is very similar from ICT netowork testing( often called penetration testing)
- Thier proposed testbed consists of these three tests.

# 7. Gillen et al (2020):  Design and Implementation of Full-Scale Industrial Control System Test Bed for Assessing Cyber-Security Defenses.

## Overview
 The developed ICS testbed is the cooling ystsem for Oak Roidge National Laboratory's 200-petaflop SUmmit supercomputer, current fastest open-science computer in the the world. THe infrastructure needed to cool this computer that draws 134MW power is about 4 thousand gallons of water per minute. The testbed is designed to mimic this industrial cooling system.

The testbed uses Allen-Bradley Control-LOgix (PLC). The HMI is an Allen Bradley PanelView Plus, and Historian is Yokogawa data acquisition unit. they connected engineering work station for controlling and configuringg historian as well as PLC.

They have over 500 sensors and actuators that orivude data the the PLC and respond to its commands. most sensor interact with PLC  via bridge. The sensors we emulated using over 40 Raspberry PIs.

Synthesis: Single vendor , no description of protocols uses, but since AB PLC, it could mean EtherNet/IP is what we build. our testbed in more heterogeneous.

# Sicard, Hotellier, & Francq (2022): An Industrial Control System Physical Testbed for Naval Defense Cybersecurity Research

## Overview
The paper presents an ICS testbed for naval defense cybesecurity research. The testbed implements a representative model of a surface warship. It consists of physical operative part( implementing level 0 of the Purdue Model) serves the main functions of the model such as propulsion, artillery. There is also digital grouping of local control( Level 1 of purdue model) and supervitory control(level 2). It represents the warship in brands of equipments: Seimens and Schnider Electric) .

Synthesis: Multi-vendor is similar to our implementation. good for diversity.

## Architecture of the Testbed

The  architecture implemented by the testbed shows four mainn functions of the ship; Direction, Energy, Artillery and Propulsion. 

- Direction Domain:  Implemented by Schnieder Electric PLC M340-20: allowing to control the direction of the ship. It involves acting on ruddler position in order to vary the ship direction.
- Energy domain: implements in Schnieder Electric PLC M580-1020, and controls filling and emptying of the furl tank.
- Artillery domain ( Seimens PLC S7-1214): Allows to take action on the 76mm gun turret model. it acts on the positining of the gun turret and ammunition firing.
- Propulsion( Seimens PLC S7-315): allowing to contorl the propulsion of the ship. the iam is to act on the propulsion propellers to vary the speed of the progress of the ship.

Each sub function is controlled by a single PLC. The differe t contorl PLCs communicate with each other via coordination PLCs( M580-3020, and S7-1516). The coordination PLCs are also used as relays for the supervitory control. Each domain function is controlled by authorized human operators: manually on the equipment, locally from local HMI, or remotely from Supervitory HMI.

The OT system are complemented by IT level corresponding to layers 3 to 5. The IT level is composed of virtual machines(VMs) either generating traffic on our ICS physical testbed or malicious traffic for attack simulations.

## Detailed Description of the Testbed:

1. Monitoring: Scada, is dedicated scada is set up. it comprise of two afomentioned PLCs, which consoladate of orders from the domain loops. ( They act as middleware architeture like the one we are proposing in our testbed?). SCADA also includes the following:
	1. Siemens Microbox IPC427D which implementsa all SCADA HMI Variables. The variables are share on one side with seimens PLCs  ( probably using S7 communication) and on the other side with Schnieder Electric PLCs using Modbus/TCP to Profinet gateway.
	2. The supervotory control HMI is the display for the seimens microbox. It represents the remote control statio and allows a global monitoring of the tstbed.
2. Direction Domain Loop: This is a dedicate function for controlling the direction of the loop. A control panel housing ICS PLC and also network equipment suich as switches and firewalls implementing the layer 1. It also includes the following:
	1. L;ocal HMI representing the Directional local contol station.
	2. aft part of a siurface fraigate containing two rudders eeach controlled by a stepper mother driven two servo drives.


Synthesis: This is a very high and detail testbed ever. It implements entire purdue model, include multi-vendors( and so multi-protocols). Its very good example of a very realistic architecture. but, ours also includes OPC-UA protocol, we want to see in presence on secure industrail IoT protocol how resilient is ICS? we also implement middleware using RPI instead of TWO PLCs, which is a lot cheaper compared to PLCs. Our PLCs share the contol of the same plant, we don't have complete different PLCs controlling completely different aspec of the plant. ours need to signal each other, there has to be PLC - TO-PLC communication. and  the quention we will be answering is, is ModbusTCP better (directly between PLCs) or  signals via middleware? which one is better? so yeah, our testbed is still filling some gaps in some sense.

# 8. Xu et al. ( 2019): MSICST: Multiple-Scenario Industrial Control System Testbed for Security Research

# Overview

The system presents multi-scenario ICS Testbed, HIL testbed for cybersecurity research. The testbed consists of four typical process scenarios: thermal power plant, rail transit, smart grid, and intelligent manufacturing.  They testbed in build using combination of physical and software simulations to build the process scenario.

In each process scenario, actual physical process is simulated by a sand table, the control system is contrustructed with commercially available hardware and software.

Synthesis: Their testbed features seimens and allen-bradley plcs control each industrial scenario. it very high detailed testbed indeed. No complains. featuring multi scenario is good because we could investigate how different industrial system will respond to certain attacks. However, their testbed connects all the different industrial system to the same enterprise network. THis is questionable as to fedility because in real- ICS, smart grid and thermal power plant are very different systems controlled and managed by completely different networks.  It would be good if they provided a way to activate one testbed at a time, allowing only to study that particular scenario at a time. we still don't see clear use of OPC UA propotocol, no layer 1 communication implements ( PLCs don't talk to each other but only to the Supervision), we again don't have inclusion of an open-souce Arduino Opta and impacts of its vulnarabilities remains unstudied. 

A part from that, this is very detailed and well build ICS testbed.