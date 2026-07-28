# Section 1: Background Information
**Open Platform Communications Unified Architecture(OPC UA)** is a platform-independent, service-oriented industrial communication protocol. It acts as a standardized translation and security layer, bridging the gap between low-level control systems(OT) and higher-level IT/Business systems (MES, ERP, cloud etc)
## 1.1: OPC UA Architecture & Communication Levels
In Industrial Automation, OPC UA is highly flexible protocol spanning across OSI model and industrial layers.
1. **Layer 1( The Field / Control Level):** OPC UA is utilized here directly for machine-to-machine(M2M) communications and exposing variable for higher-layer consumption.
2. **Layer 2 ( Supervisory / Manufacturing Execution Level):** OPC UA operated here as a data aggregator, security poling data from layer 1 devices via its standardized Client-Server or Publish-Subcribe architectures.
## 1.2 Inter-Layer Communication
1. **Layer 1 to Layer 1 (M2M):** Controller can simulteneously as OPC UA Servers and Clients. One PLC queries data from another's server, providing true vendor-agnostic controller-to-controller communication without proprietary network buses.
2. **Layer 1 to Layer 3(Vertical Integration)**: Layer 1 PLCXs expose thier data as an OPC UA address space, then Layer 3 (SCADA/MES) systems run OPC UA clients tto browser the nodes, read variables, subscribe to data-change notifications, or invoke controller methods.
# OPU UA Core Concepts
 - In Modbus, there is flat register addresses,no meta data, no security,master/slave polling.
 - OPC-UA is exact opposit Philosphy. The following the Four Key Ideas of the OPC-UA:
	 1. **Address Space**: Instead of pure registers, OPC-UA exposes a hierarchical, self-describing tree of Nodes. Each Node has _NodeId_, _BrowseName_, and _NodeClass_(has variables, objects, methods and so on). There is no need for a separate spreasheet of register mappings. The Server tells the client what each tag is.
	 2. **Server/Client roles**: In OPC UA. "server" simply means "data source", and a single device can be both a "server" and "client" simultaneously. ( "Very good for PLC's to speak to one another.)
	 3. **Security Policies**: OPC-UA defines _endpoints_ each with _SecurityPolicy_ and _MessageSecurityMode_. 
	 4. **Subscriptions & Polling**: Modbus is pure poll ( mean you ask, it answers). With OPC UA, this is also supported ( __Read__ or __Write__ services), but is also support subscriptions. __Subscriptions__ allow the client to say "tell me when this values changes", and the server pushes updates ( without the client requesting to for data manually, this could save tremendous amount of controller-to-controller latency). 
	 
## OPC UA Node: 
 In OPC UA, A Node is a foundational Building Block of information. It is very similar of  *Object-Oriented Programming*  concept in that it represents the real physical equipment (like Sensors or PLCs),metadata,as well as relationships between them. Each Node leaves in server's address space, and there are eight distinct Node classes, that serve a specific purpose.
### Types of OPC UA Node Classes
#### 1. Object:
This Node represents physical components such as specific "Motor", "Tank". They do not hold values themselves, but can group together variables and methods.
#### 2. Variable
This represents actual user data, states, or properties ( e.g., a Temperature reading or serial number). These Nodes hold real-time or historic data.
#### 3. Method
This represents an executable function or command ( e.g., "Start", "Reset" command)
#### 4. ObjectType, VariableType, & ReferenceType:
These define the templates or classes for standarddizing instances. For examle, defining the general structure of a "Pump", so that is can be re-used multiple times.
#### 5. DataType
Defines the type of data a variable holds. (e.g., Integer, Float, etc)
#### 6. View:
This is a filtered subset of  the address space designed to show clients only the specific information.


## The Concept of OPC UA Subscriptions
 - Instead of client continuously polling data fromthe server, OPC UA subscription concepts allow a more cleaner and elegant functionality. The client can subscribe to a set of Nodes that the server monitors. Only when their values change will the server notify the client about such changes.
- This tremendously reduces the amount of bandwidth usage,and offers other important functionalities.
- The client can subscribe to several Nodes at the same time. These are bundled into a group of information source called Monitored Items, forming a piece of information called a Notification.
- There are different types of "changes" that a client can subscribe to. Examples include, subscription to data changes  of Variable Values, subscription to Events of Objects, or subscription to aggregated values.


# OPC UA (Siemens)
 - OPC UA is open, platform-independent, and scalably flexible protocol for secure industrial communications.
 - It supports authentication, authorization, and encryption in addition to data transfer.
 - It can run on exisiting PROFINET Infrastructure without compromising performance, or downtimes.
 - SIEMENS combines OPC UA with PROFINET forming a common Industrial Ethernet network. It relies on OPC UA as interface from control level(layer 1) to higher-level( SCADA(layer 2) , Manufacturing Execution Systems(MES) layer 3, and Enterprise Resource Planning(ERP) layer 4&5 (IT).
 - Key Benefits of OPC UA:
	 1. Vendor independent integration: It enables seamless communicationa across devices from different vendors and platforms.
	 2. Built in security features: Data is encrypted.
	 3. Scalable end-to-end communication: It connect devices across all automotion levels(Purdue Model) from field control to cloud.
## Configuration on S7-1200 PLCs 
### Overview
- OPC UA is supported on S7-1200 PLCs with firmware version 4.4 or higher.
- The PLC enables data access by supporting configuration as an OPC UA Server( only Server). This means it can not be configured as 
- 