#include <AlPlc_Opta.h>

/* opta_1.0.6
*/

struct PLCSharedVarsInput_t
{
};
PLCSharedVarsInput_t& PLCIn = (PLCSharedVarsInput_t&)m_PLCSharedVarsInputBuf;

struct PLCSharedVarsOutput_t
{
};
PLCSharedVarsOutput_t& PLCOut = (PLCSharedVarsOutput_t&)m_PLCSharedVarsOutputBuf;


AlPlc AxelPLC(1758719799);

// shared variables can be accessed with PLCIn.varname and PLCOut.varname

// Enable usage of EtherClass, to set static IP address and other
// #include <PortentaEthernet.h>
// arduino::EthernetClass eth(&m_netInterface);

#include <PortentaEthernet.h>
EthernetInterface eth_interface;
arduino::EthernetClass eth(&eth_interface);
void setup()
{

	// Configure static IP address
	IPAddress ip(192, 168, 50, 30);
	IPAddress dns(8, 8, 8, 8);
	IPAddress gateway(192, 168, 50, 0);
	IPAddress subnet(255, 255, 255, 0);
	// If cable is not connected this will block the start of PLC with about 60s of timeout!
	eth.begin(ip, dns, gateway, subnet);


	AxelPLC.InitFileSystem();

	AxelPLC.Run();
}

void loop()
{

}
