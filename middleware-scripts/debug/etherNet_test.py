from pycomm3 import LogixDriver

# IP Address only (Micro820 does not use backplane/slots)
MICRO820_IP = '192.168.50.20'

with LogixDriver(MICRO820_IP) as plc:
    # 1. Verify connection & dynamic tag upload
    print(f"Connected to: {plc.info['product_name']}")
    
    # 2. Direct symbolic read (Global Variables defined in CCW)
    result = plc.read('SchneiderModbusHandshake', 'Schneider_Handshake_ACK')
    print(result)

    # 3. Direct symbolic write
    plc.write(('Target_Setpoint', 1.0))