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

