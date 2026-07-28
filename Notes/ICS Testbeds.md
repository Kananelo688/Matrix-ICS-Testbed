## Surveys
## 1. Conti, Donadel, & Turrin A Survey on Industrial Control System Testbeds and Datasets for Security Research
- **Operational Technology:** Software and Hardware used to monitor and control industrial equipments, assets, processes, and events.
- **Information Technology:** Consists of hardwaren and software used to manipulate, store, and protect information.
- OT & IT were originally disconnected, however the IT/OT Convergence result in the interconnection of these two domains, creating new vulnerability surfaces.
- Since ICS control physical processes, sometimes dangerous like chemical or nuclear plants, security of such systems is often very critical.
- Successful attacks on ICS imply huge economic impact on the organisation: This includes operational shutdowns, damage to expensive equipment, business reputation and so on.
- Security-by-design approaches are thus needed to mitigate these attacks. However these require a complete and realistic testing infrastructure. This is where scaled-down versions of ICS (testbeds) are used.
-  Testbeds are classified into Physical, Virtual, or Hybrid
	- **Physical Testbeds**:uses real hardware amd software to configure both network and physical layers. They are suitable choices when realistic data and latencies in critical. However, they are expensive both in construction and maintenance.
	- **Virtual Testbed**: These leverage software simulations and emulations with single or multiple programs to reproduce the entire network and all different components. It represents low cost solution, but not ideal for simulating high fedility physical processes due to the virtualized environment.
	- **Hybrid Testbed:** This approach uses combination of both physical devices and software simulations. It is a good trade-off between physical and virtual solutions.
## 2. Geng et al - A survey of industrial control systems testbed
- Outbreaks of ICS attacks such as Stuxnet, Duqu, Flame, Blackenergy, Triton make information security of ICS a critical research question that needs to be addressed.
- ICS saftey testing helps ensure safet operation at industrail msites, but  high availability requirements( small downtimes) make it very difficult to conduct research on actual industiral plants. Thus, testbeds are often build to simulate or emulate real ICS and deploy safely executed experimental environment.
- Four general requirements for designing industrial control systems testbeds:
	- **Fedility:** The testbed needs to reproduce or replicate the real system are accurately as possible.
	- **Repeatability:** The testbed should ensure that the same repeated experiments results in the same or statistically consistent results.
	- **Measurement Accuracy:** The testbed should be able to accurately monitor the experimental process and should not interfere with with the experimental results when performing observation and test actions.
	- **Safe Execution**: The testbed should ensure that the activities in the tstbed are isolated, and that tyhe experiment does not have devastating effects on the physical system or personal safety.
-  They also classifty testbed into physical, virtual and hybrid.


# Review of Existing ICS Testbeds
## 1. Azimi, Sami, & Khalili - A Security Test-Bed for Industrial Control Systems
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

## 2. Morris(2011) - A control system testbed to validate critical infrastructure protection concepts
- The paper presents the design and use of ICS cybersecurity testbed developed at Mississippi State University. 
- Unlike many that rely on simulation, this one combines:
	- commercial PLCs, Commercial HMI Software, real industrial communication protocols,
	- real physical processes, and laboratory-scale industrial plants.
- The fundamental philosophy behind this testbed is: **discover vulnerabilitiies** -> **develop explopits -**> **study physical consequences** -> **develop defenses** -> **validate defenses and real equipment.**
- Why was the testbed developed: The authors identify that many orevious scada etsbeds are simulated PLCs, networks, and physical processes. These can not accurateky model firmware behavior, protocol implementation bugs, hardware timing, physical process interactions, and vendor-specific vulnerabilities.
- Thus, the build the testbed using laboratory using actual industrial equipment: the testbed supports cybersecurity research, education, workforce training, and validation of new security mechanisms.
The testbed architectre is actuallu two LABs connected together:
Lab 1:
	Lab 1 is industrial process laaboratory. It contains water storgate tank, raised water tower, factory vonveryor, gas pipeline, industrial blower, and steel rolling mill.
Lab 2:
	The second Lab 3 is power and energy research laboratory. it contains electricval substation, PMUs, protection relays, RTDs, historian, and smart grifd equipment. 
These two lab work together forming integrated research platform.
The authors model multiple critical infrastructures instead of focusing solely on one testbed.

They used two PLC families: Control microsystem SCADAPack LP(low-power Remote Terminal Unit-RTU, and the Programmable LOgic Controller-PLC, supports MODBUS, and DNP3 protocols) and Allen Bradley CompactLogix L35X ( This is second generation Programmable Automation Controller PAC from Rockwell Automation designed fro small to medium-range industrial applications.It supports EtherNET/IP).

The HMIs used are GE fanuc iFIX (serial system), and FactoryTalk View(Ethernet system)
**FactoryTalk View:** This is HMI software by Rockwell Automation used to monitor, control, and visualize industrial automation process. This connects directly to Allen-Bradley programmable Logic controllers.

The protocols used include: EtherNet/IP, Modbus ( not OPC UA), it still limited interms of heterogeniety of protocols, and having less secure protocols is kinds limiting. questions such as: what ways can layer 1 controllers be compromized if the only protocol to between layer 1 and layer b2 is secure OPC UA? Is OPC UA fully secure enough to protect the critical infrastructure at all layers?

But overall, this is a very power testbed, that simulates a real system using real physical hardware.

## 3. Green 2017: Ten Lessons from Building an Industrial Control Systems Testbed for Security Research

The paper is fundamentally different from many ICS testbed papers. It not introducing a new security technique, but rather a reflection paper that document authr's practical experience after three years of designing, building, operating, and maintaining an ICS security testbed.

The central message of the paper is : Building an effective ICS security testbed is not simply about buying PLCs and connecting them together. It requires carefully balac=ncing three competing objectives: **"Diversity"**, **"Scalability",** and **"Complexity".**

Every design decision affected these three properties: Adding more PLC vendors increases diversity. More vendors also increase configuration difficulty(complexity), and buying more hardware improves realism, but reduces scalability because of cost.

The main design principles:
1. **Diversity:** A good ICS testbed should represent the real industrial world. This means supporting different PLC manufacturers, different industrial protocols, legacy devices, modern devices, homogeneous plants, and heterogeneous plants. Without these diversity, research results may only apply to one vendor.
2. **Scalability:** ICS laboratories are very expensive. The challenge is: "How do you build a larger laboratory without buying hundreds of PLCs". The authors discuss several approaches: Virtual Machines, VLANs, Hardware-in-the-Loop, Hot-Swappablle hardware.
3. **Complexity**:  As the testbed grows, it becomes more difficult to maintain. It may bbe difficult to understand the network, configure devices, repeat experiments, and manage multiple users.

The Ten Lessons Learned:
1. Lesson 1: Device and Technology selection should be market-driven. The authors initially built thier testbed around a single PLC vendor,  but later realized it was a mistake because real industrial environments cointain equipment from many vendors, and with varying protocols.
2. Lesson 2: The real factories are both homogeneous and heterogeneous. some plants use only seimens PLCs, others use Seimens + Allen Bradley + Schnieder together. A good testbed should support both. The key takeaway is that flexibility is essential because real factories evolve over time, rather then being built all at once.
3. Lesson 3: process diversity is less important that hardware diversity. The authors note that some researchers built extremely realistic process, which are impressive but very difficult to modify. Choosing a simple realistic process is more preferable because its easy to replace or add new components.
4. Lesson 4: Hardware-in-the-loop(HIL) uses mathematical modelsto simulate physical processes, and the authors noted that it is not essential. They argue that accurate moedl are difficult to develop, sensor behavior is difficult to reproduce, and noise an timing are hard to model. The key takeway is that real hardware often provides  more reliable experiemental results than the HIL for ICS security.
5. Lesson 5: Simulations should not replacse industrial devices. They note that software simulation can not accurately reproduce PLC firmware, vendor-specific behavior, communicating timing, and implementation bugs. Therefore, real PLCs are preferred whenever possible. Simulation should only supplement physical hardware.
6. Lesson 6: Virtualization and VLANs greatly improve scalability. Instead of purchasing many physical servers. Authors use VMware, VLANs, an virtual machines.
7. Lesson 7: Use a dedicated management network. Researchers should d not have to connect separatrely every evice. instead, all administration should occur thropugh one management network.
8. Lesson 8: Separate manufacturing zones. Instead of building one enormous ICS, authors advice it into several manufacturing zones. The benefit is that multiple experiemtns can run simulteneously, easier troubleshooting, and improved realism.
9. Lesson 9: Document everything while building.
10. Lesson 10: Optimize data logging for security.

## 4. Reaves & Morris (2012) - An open virtual testbed for industrial control system security research

This paper is continuation of Morris(2011) physical testbed paper. While the 2011 paper argues that the physical testbes provbide the bhighest rrealism, this paper addresses a practical limitation that physical ICSs testbeds are expensive, difficult to expand, and inaccessible to many researchers. The paper therefore proposes an open, virtual ICS tesbeddd that preserves much of the behavoir of real ICS while dramatically reducing cost and improving accessibility.

The main contributions of the paper includes the following:
1. an open virtual ICS platform: platform esigne so researchers can download, modify, and extends it instead of creating new testbed from scratch.
2. Modular Virtual Devices: The software builds independent software versions of industrail devices such as PLCs, RTUs, HMIs, and so on.
3. The testbed supports: purely virsual experiments, hybrid, and migration towards fully physical systems.
4. The testbed was verified with ealier physical testbed.


