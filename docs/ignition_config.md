# Configuration Procedure for Ignition Scada:

Ignition is built around the idea that everything flows throuugh the **Tag system**. As a result, Tags need to be understood deeply before doing HMI or historian (where are just consumers of Tags)

## Layer 1 - The Gateway
 The gateway is the Ignition server process running on PC. It handles everything: OPC-UA connections, tag managaments, historian storage, serving HMI to browsers and so on. It is configured through the Gateway webpaghe at ```http://localhost:8088```. It can be though as the BRAIN of the SCADA Systems.

Important: You will never design HMI screens in the gateway, but everything that the HMI depends on can be configured here first.

## Layer 2 - OPC UA Connection

Before any tags can exists, Ignition's Gateway needs to be told where to find data. In our case, this will Raspberry Pi's OPC UA server at: `opc.tcp://192.168.30.100:4840`. This is an OPC UA Device Connection in Ignition. Once connected, Ignition can browse the entire `MATRIX/` address space and see every node defined in `opcua_server.py`.

## Layer 3 - Tags

In Ignition, a Tag in internal representation of one data point. It has a name, datatype, a value, a quality(good, bad or uncertain), and a timestamp. Tangs live in **Tag Browser** in Ignition Designer. There are two kinds of Tags relevant to our project:  
1. **OPC Tags** - These are linked in a specific OPC UA node in RPi. When the node's value changes on RPi, the tag value updates in Ignition automatically via subscription. 
2. **Memory Tags:** These are not connected to any device. Used for internal logic, operator set  points, calculated values.
## Layer 4 - Historian (Tag History)
 The historian is just a setting on a tag. When you enable Tag History on OPC Tags, Ignition starts recording every value change ( on fixed interval) to its internal database (which in SQLite by default, but we can connect a proper database for your research).  This time-series database in our anomaly detection dataset. 
THIS IS THE MOST IMPORTANT THING TO CONFIGURE CORRECTLY: Once experiments are run, one can not go back and add history to tag you forgot to enable.

## Layer 5 - Perspective HMI

Perspective is Ignition's web-based HMI designer. We build Views(Screens) using components (Labels, indicators, charts, and buttons). Each components has bindings(  expressions that link component properties - color, text, value, to tags.). When a tag value changes, the binding fires and component updates.

We do not write pooling loops, we just define bindings, and it will update automatically(Which saves us a whole lot of energy.)

## Build Step for The Testbed:

1. Gateway webpage: This is where you configure OPC UA Connection that points to RPI.
2. Tag Browser(Designer): 
	1. You can Browse the OPC-UA Device and drag nodes into the tag tree. 
	2. We can organize into folders: e.g Turntable/, TransferUnit/, or Conveyor.
	3. Enable Tag History on every tag you need for experiments.
3. Historian:
	1. Configure a database connection (Even SQLite is fine)
	2. Confirm tags are recording (Check Tag History in Designer)
4. Perspective HMI
	1. Build Overview screen (plant diagram with live indicators)
	2. Build Historian screen (time-series chart showing all tags)
	3. Build Alarm screen (configure alarm pipelines on key tags)

Notes: Never start Building HMI screens before steps 1 - 3 are done.

