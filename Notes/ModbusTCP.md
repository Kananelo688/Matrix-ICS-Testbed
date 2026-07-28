#  Chaper 1: Background Theory on ModbusTCP Procotol
## 1. Introduction
Modbus TCP is an industrial Ethernet Communication Protocol that adapts the classic Modbus master/slave logic into a standard, connection-oriented client/server model. It allows smart devices, PLCs, and SCADA systems to exchange raw data reliably over the standard local area networks.
## 2. The Core Data Tables
Modbus data is stored in four logical memory tables. Each table is theoretically capable of holding up to 65,536 elements (addresses from 0 to 65,535). However, the practical size of the memory tables is usually much smaller than that.
### 2.1 Types of Memory Tables:
-  **Coils (Read/ Write):** These are binary-states (1-bit ON/OFF)
-  **Discrete Inputs (Read-only):** These are Binary states that usually driven by external hardware (e.g.,  limit switches).
- **Input Registers(Read-only):** 16-bit numerical values, often from sensors or measurements (e.g temperature)
- **Holding Registers(Read/Write):** 16-bit general-purpose data that define the system states, or parameters (e.g setpoints)
### 2.2. Holding Registers in Depth:
The holding registers are the most versatile memory space in Modbus. Because they are 16-bit integers, they take values from 0 to 65,535 (unsigned) or -32,768 to 32,767(signed)
- **32-bit Values:** Many industrial variables (like floating-point numbers or high-resolution counters) require 32-bits, they are stored across two contiguous holding registers.
-  **Function Code:** To interact with the holding registers, specific function code are used by the client.
	- 0x03: Code for "Read Holding Registers"
	- 0x06: Code for "Write Single Register"
	- 0x10: Code for "Write Multiple Registers"
## 3. Roles of Client
The client ( which is analogous to old serial Master) is the initiator of the communication.
	1. **Queries:** It actively polls for data or pushes commands. A client can be Human-Machine Interface (MHI), a SCADA system, or another logic controller.
	2. **Connection Management:** It creates sockets, manages the transmission and times out requests if the server fails to reply in time.
	3. **Packet Construction:** It assembles the Modbus message, wraps it in a Modbus Application Protocl(MBAP) header, and sends it to the TCP stack.
## 4. Roles of the Server
The server , analogous to old serial Slave, is the responder.
1. **Passivity: I**t never initiates a communication. It only listens on a designated network port, and waits for an incoming query. A server is typicall a small meter, and I/O Module, and a motor drive.
2. **Execution:** Once it recieves a properly addressed packet from a client, it unpacks it, executes the required commands, sends the requested data or confirmation back to the client.
## 5. Connection Setup & The TCP Stack
Unlike the serial networks that broadcasts messages ove the shared bus, Modbus TCP relies heavily on standard Ethernet and TCP/IP, esuring packets are reliable and sequenced.
### 5.1. TCP Handshake:
Modbus TCP Server listen for incoming TCP connections on registered **Port 502**.
1. **TCP Connect:** The client initaites the standard 3-way handshake (SYN->SYN/ACK->ACK) with the server's IP address.
2. **Persistent or Transient Connections:**  The TCP connection can be kept open indefinitely, allowing for quick, continuous polling, or the client can close in after every transaction.
3. **Multi-client Support:** a single server can handle multiple active clients querying its registers simulteneously, provided the hardware allows it.
# Chaper 2: Configuring ModbusTCP On Seimens S7-1200

With background theory explained in the previous chapter,we will now configure and play around with this protocol in detail.
## 1. Configuring Seimen's PLC as Modbus TCP Server:
To configure the PLC as a a server, setup the project as usual on Portal TIA, and then follow the following Steps:
1. Create Master Database: open "program block" then select "Add new" and select **"Data Block"**
2.  Such as block will open up in the main window, we now want to create the variables for the registers of Modbus. You can think of this block as "Memory Table" of the Modbus Register. The following variables of this Data Block  were created:
	1. **Holding Register:** Create an Array on integers that define the Holding registers. The data type should be integers ( as per the previous chapter).
	2. **Connect:** This should be on type "TCON_IP_v4", and is used open up the TCP Modbus port. Set its field as follows:
		1. *InterfaceId:* set to 64
		2. *ID*: set to 1
		3. *ConnectionType:* 11(other types are 19 UDP, 17 or 11 TCP/IP)
		4. *LocalPort* as 502 (this port is used by  Modbus TCP)
	3.  **Error:** This is of Bool type and will be used to handle the errors in Modbus Configuration
	4. **Status:** This is a variable of type "Word" and is used to monitor the status of Modbus Communication
3. After creating the block, openthe main block "Main(OB1)" by double clicking on it.
4. Navigate to Panel on far right: "Instruction Panel" -> "Communication" -> "Others" -> "MODBUS_TCP", and then copy the "MB_SERVER" to the rung of the "Main(OB1)" block. 
5. Map the interfaces of "MB_SERVER" to the variables of the "Data Block" created in step 2 as follows:
	1. "MB_HOLD_REG" -> "Data Block name"."holding register name"
	2. "CONNECT"-> "Data Block name"."Connect variable name"
	3. "ERROR"  -> "Data  Block name"."Error variable name"
	4. "STATUS"  -> "Data Block name"."Status variable name"
6. Leave other interfaces to their default values, unless used for other purposes.
7. Save the project and click compile  button.
8. Right click on the "Data Block" -> "Compile" -> "Software (only changes)" to compile the data block
9. Then compile the project yet again.
## 2. Configuring Seimen's PLC as Modbus TCP Client

# Chapter 3: ModubusTCP configuration of Allen-Bradley PLC (Micro820)

## 1. Modbus TCP Server Configuration
The  Modbus Server means, it exposes register to the network to be written or programmed by other devices in the network.
To confugure Modbus TCP Server on Micro800, follow the following steps:
1. Open Connected Components Workbench, ans create a new project as usual.
2. Open "Global Variables", and define Modbus Registers that you intend to use. (Booleans are coils,while Int are understood as holding registers)
3. Double click on "Micro820" to open the PLC'sconfiguration Panel.
4. Open "Ethernet" configurations,st up IP addresses, adn be sure to check "Server State" under "Modbus TCP section".
5. Now open "Modbus Mapping", and add the registers you created in step 2. Assignment them address, that you will be using in your program.
6. Create new program and access Modbus registers that you want when you need to based on the logic.
## 2. Confuguring PLC as Modbus Client
This means it is configured to write or read from other devices over the Modbus Protocol.


# Chaper 4: Modbus TCP Configuration on Arduino Opta
## 1. Modbus TCP Server Configuration.

