# 1. Song, Nguyen, Irvine(2025) - A Zero Trust Architecture for Critical Operational Technology Systems

### 1. Summary of the Paper

The authors argue that Zero Trust(ZT) technology appears to be understudied in Literature. They present a Zero Trust model to mordernize legacy OT systems, using Using Water Treatment as a case study.

They evaluated the Zero Trust architecture against real-world remote-access, and bring-your-own-device(BYOD) use cases.

The paper addresses the growing exposure of Operational Technology (OT) / Industrial Control Systems (ICS) to external networks due to remote monitoring, vendor maintenance, and IT/OT convergence. Traditional perimeter-based protections (physical isolation and coarse network segmentation via the Purdue model) are no longer sufficient.

While Zero Trust (ZT) has been widely adopted in IT environments, its application to OT remains under-explored. The authors propose a Zero Trust OT (ZT-OT) architecture tailored to the constraints of critical OT systems (legacy devices, high availability requirements, limited computing resources, and safety priorities).

They instantiate the architecture on a water treatment plant, develop a threat model focused on remote access and Bring-Your-Own-Device (BYOD), define access policies using Policy Enforcement (PE) levels and dynamic risk profiles, and evaluate the design against realistic use cases. Results show that ZT-OT can mitigate specific remote-access and BYOD threats, but also reveal important limitations related to legacy components and impacts on normal operations.

### 2. What Testbed / System is Being Used

The authors base their design and evaluation on the **Secure Water Treatment ([[Testbeds in Literature]])** testbed architecture developed at the Singapore University of Technology and Design (SUTD).

SWaT is a well-known, fully functional, scaled-down water treatment plant that implements a six-stage process to produce potable water. It combines legacy OT components (PLCs, sensors, actuators, SCADA) with modern IT systems and is widely used in ICS cybersecurity research.

The paper uses a **hypothetical water treatment plant (WTP)** that follows the SWaT architecture as the concrete instantiation for analysis. The system is treated as an IT-OT integrated network that must support both on-premises operations and the new requirements of remote connectivity and BYOD.

### 3. How the Zero Trust Architecture is Implemented

The ZT-OT architecture extends the classic NIST SP 800-207 model (Policy Enforcement Point – PEP, Policy Decision Point – PDP, Policy Information Point – PIP) to the specific needs of OT:

- **Network segmentation into three enclaves** based on criticality:
    - IT network zone
    - OT network zone
    - Trusted zone (contains legacy devices that cannot support full ZT)
- **Policy Enforcement (PE) Levels**:
    - PE Level 1 – non-OT / lower criticality zones
    - PE Level 2 – zones with OT functions
    - PE Level 3 – trusted zone (legacy, latency-sensitive, or resource-constrained components)
- **Dynamic risk profiles** for every subject (user + device + application): Low, Medium, High, or Very High risk. Profiles are continuously reassessed.
- **Access policies** (Table 2 in the paper) that become stricter with higher PE levels. For example:
    - PE Level 3 allows only low-risk company-furnished equipment, no remote connections, and no external devices.
    - Software agents on devices are preferred but made optional for personal devices (with restrictions: read-only access on non-critical systems if no agent is present).
- **Dual PDP design**: An enterprise PDP and a local plant PDP so that each water plant can continue operating even if the link to the enterprise network is lost.
- PEPs are placed at the boundary of every zone. SCADA and Historian servers are relocated into the control network to keep the plant self-sufficient.
- Logging is strengthened and all log requests are also mediated by the PEP/PDP.

The design deliberately relaxes some NIST recommendations (e.g., mandatory software agents) to accommodate the realities of OT and personal devices.

### 4. How It Is Evaluated: Test Cases and Results

Evaluation is performed through **security analysis of three use cases** on a hypothetical instantiation of the ZT-OT architecture (best-case scenarios under the stated assumptions). The use cases focus on the two main new capabilities the architecture is intended to enable:
- Secure **remote access** (telework, remote maintenance, centralized monitoring of satellite sites)
- Secure **BYOD** (personal devices used locally or remotely for business purposes)

**Key findings**:
- The ZT-OT architecture successfully mitigates many of the threats associated with remote access and BYOD that were identified via the MITRE ATT&CK for ICS framework (particularly Initial Access vectors).
- Continuous verification, least-privilege (JITA/JEA), risk-profile-based decisions, and zone-specific PE levels significantly reduce the attack surface and limit lateral movement.
- However, the authors explicitly identify **limitations**:
    - Legacy components that cannot be updated, patched, or instrumented with agents remain difficult to fully protect.
    - Some impacts on normal day-to-day water treatment operations were observed (availability and operational friction).
    - Full Zero Trust is not always feasible on the most constrained or safety-critical devices.

The evaluation is primarily analytical (threat-model-driven use-case analysis) rather than a large-scale empirical attack campaign on a live physical testbed. (This is a limitation)

### 5. Key Takeaways from the Paper
- Zero Trust **can** be applied to critical OT systems and offers clear security benefits for enabling modern requirements such as remote access and BYOD.
- A pure IT-style ZT implementation is not suitable; adaptations are required (relaxed agent requirements, PE levels that reflect OT criticality, dual enterprise/plant PDPs for resilience, special treatment of the trusted/legacy zone).
- Legacy devices remain the hardest problem. Zero Trust helps contain the risk they introduce but cannot fully eliminate it without complementary compensating controls.
- There is a real trade-off between security gains and operational impact. Any ZT-OT design must carefully balance cybersecurity with the high-availability and safety priorities of OT.
- The paper provides one of the more concrete early architectural blueprints (with explicit PE levels, risk profiles, and dual-PDP design) for applying Zero Trust to water treatment and similar critical infrastructure OT environments.
- Future work is needed on non-ideal scenarios, deeper empirical validation, and handling of devices that cannot support continuous verification.

In short, the paper demonstrates that Zero Trust is a promising direction for modernizing OT security, but successful adoption requires careful tailoring to the unique constraints of industrial control systems rather than a direct transplant of IT Zero Trust practices.








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