# Getting Started with Arduino Opta on Arduino IDE (Linux)

The tutorial followed in from [finder relaying innovation](https://opta.findernet.com/en/tutorial/getting-started)

## Goals:
1. Learn how to programm Opta with Arduino IDE.
2. Learn how to program status LEDs, programmable button, control inputs, and outputs.
## Set up Instructions
1. Download lastest version of IDE ( AppImage for Linux distributions)
2. Install Core for Opta: *Tools* -> *Board* -> *Board Manager* and then search for **opta embed** and install it.
## Testing the Setup is working:
We will use the simple sketch that blinks the status LEDs from 0 to 3 in sequence.
```
/**
  Getting Started with Opta™
  Name: LED_Blink_Opta
  Purpose: Blink STATUS LEDs on Opta™.

  @author Arduino
*/

void setup() {
  pinMode(LED_D0, OUTPUT);
  pinMode(LED_D1, OUTPUT);
  pinMode(LED_D2, OUTPUT);
  pinMode(LED_D3, OUTPUT);
}

void loop() {
  digitalWrite(LED_D0, HIGH);
  delay(100);
  digitalWrite(LED_D0, LOW);
  delay(100);

  digitalWrite(LED_D1, HIGH);
  delay(100);
  digitalWrite(LED_D1, LOW);
  delay(100);

  digitalWrite(LED_D2, HIGH);
  delay(100);
  digitalWrite(LED_D2, LOW);
  delay(100);

  digitalWrite(LED_D3, HIGH);
  delay(100);
  digitalWrite(LED_D3, LOW);
  delay(500);
}
```
Opta Core LED naming:
- **LED_D0-3** refers to status LEDs 1 - 4.
- **LED_RESET** - LED above the reset button.
- **LED_USER** - LED above the programmable user button.
Code Sketch Loading Procedure:
1. Open the IDE In terminal: ``` ./arduino-IDE.AppImage --no-sandbox```
2. Past the code above in the sketch
3. Connect the Opta to the computer and put it to Bootloader mode: (Double clicking the reset button)
```sudo cp /tmp/.mount_arduinaa0r26/resources/app/node_modules/dfu-programmer/linux/99-arduino.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If that fails run:
```
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2341", MODE="0666"' | sudo tee /etc/udev/rules.d/99-arduino.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```
4. Now download the sketch and the status LEDs will blink in sequence one by one..
## General Information about the Opta Core
- User button is defined as **BTN_USER**, with default value of **HIGH** (when not pressed), and **LOW** when pressed.
- Note to always Change the 
## Sketch to blind LEDs in different Orders based on the pressed status:
```
/**

Getting Started with Opta™

Name: Programmable_Button_Opta

Purpose: Configures the programmable button to control STATUS LED sequence.

  

@author Arduino

*/

  

int buttonState = 0;

int counter = 0;

int dir = 0;

void setup() {

// Initialize OPTA LEDs

pinMode(LED_D0, OUTPUT);

pinMode(LED_D1, OUTPUT);

pinMode(LED_D2, OUTPUT);

pinMode(LED_D3, OUTPUT);

pinMode(BTN_USER, INPUT);

}

  

// The loop function runs over and over again while the device is on

void loop() {

// buttonState = digitalRead(BTN_USER);

// if(buttonState == LOW){

// if(counter < 4){

// counter++;

// }

// else{

// counter = 0;

// }

// delay(100);

// }

// changeLights();

  

if (buttonState == LOW && dir == 0){

way1();

dir = 1;

}else if (buttonState == LOW && dir == 1){

way2();

dir = 0;

}

}

  

void reset_leds(){

digitalWrite(LED_D0, LOW);

digitalWrite(LED_D1, LOW);

digitalWrite(LED_D2, LOW);

digitalWrite(LED_D3, LOW);

}

  

//function that blind LEDs from 0 to 3

void way1(){

reset_leds();

digitalWrite(LED_D0, HIGH);

delay(100);

digitalWrite(LED_D0, LOW);

digitalWrite(LED_D1, HIGH);

delay(100);

digitalWrite(LED_D1, LOW);

digitalWrite(LED_D2, HIGH);

delay(100);

digitalWrite(LED_D1, LOW);

digitalWrite(LED_D3, HIGH);

delay(100);

}

  

void way2(){

reset_leds();

digitalWrite(LED_D3, HIGH);

delay(100);

digitalWrite(LED_D3, LOW);

digitalWrite(LED_D2, HIGH);

delay(100);

digitalWrite(LED_D2, LOW);

digitalWrite(LED_D1, HIGH);

delay(100);

digitalWrite(LED_D1, LOW);

digitalWrite(LED_D0, HIGH);

delay(100);

}

/**

Function to control STATUS LED based on the counter.

*/

void changeLights() {

switch(counter){

case 0:

digitalWrite(LED_D0, LOW);

digitalWrite(LED_D1, LOW);

digitalWrite(LED_D2, LOW);

digitalWrite(LED_D3, LOW);

break;

case 1:

digitalWrite(LED_D0, HIGH);

break;

case 2:

digitalWrite(LED_D1, HIGH);

break;

case 3:

digitalWrite(LED_D2, HIGH);

break;

case 4:

digitalWrite(LED_D3, HIGH);

break;

}

delay(100);

}
```

## Opta Output Relays
-  Opta has four Norminally open electromechanical Relays with capacity of 10A, 250V.
-  (This means that Opta does drive 24VDC output directly, but may do so with the assistance of Relays- Understanding how Relays Work is very critical.)
-  Opta Core identifies thes coils as: D0-D3 or RELAY1-RELAY4(alias names)
- The outputs needs to be connected by "bridging" by connecting the power cable on one size, and load on another terminal. ( They can't drive High Voltages directly like PLCs can)
-  To use the Relays, the Opta needs to be powered by a 12-24VDC. 
- Relays are activated by digitalWrite() function just like we would to with any output out status LEDs.
## Opta Inputs
- Opta has 8 input pins which can be configures to work as either digital inputs or analog inputs.
-  Pin naming in Opta Core is A0-7 or PIN_A0-7 (ALIAS).
- Analogue value ranges of the pin ranges between 0 and 10V.
- use pinMode(PIN, MODE) to set digital pin modes in setup() function. or use analogReadResolution() with resolution that you want for analogue readings.(You need to go and test these things in the Lab to be sure that the system really works).
- The  maximum voltage that can be read by microcontroller is 3V. This is important for calculating the input voltage in conjunction with the read voltage.
- The resolution can be configured inside the program, and can range between 12 ant 16 bits.
- Read Analogue Voltage using  ```analogRead```
Code:
setup function
```
void setup(){
	//Useful so that data can be displayed easily to the 
	Serial.begin(9600);
	
	analogReadResolution(16); //Resolution in between 12-bits to 16-bits
	
}
```

  snippet to read the analog input
  ```
  void loop(){
	  int sensorValue = analogRead(A0); //Read first input
	  float voltageA0 = sensorValue * (3.0/4095.0)/0.3; // this formula convert
  }
  ```
  Formula:
  $digital\_code = \lfloor \frac{V_{in}}{V_{ref}}\times 2^n \rfloor$
  
  $voltage = V_{ref} \times \frac{Digital\_code}{2^n}$
  
# Arduino Opta Notes

- This has three  variants: Opta lite, Opta RS485, and Opta Wifi. They onoy differ in connectivity capabilities,but all can connect to a standard ethernet network.
- The board can be programmed in Arduino IDE (using C/C++), and Arduino PLC IDE  which can be used to program the device in IEC 61131-3 standard languages.
- PLC IDE allows one to manage communications and protocols such as Modbus RTU and Modbus TCP effortlessly.
- All Opta devices feature an onboard low-power 10BASE-T/100BASE=TX Ethernet physical layer(PHY) transceiver.
- Mbed OS Opta has built-in library that lets one use this port out of the box.
- Ethernet connection uses pre-defined static IP address( does it, always?)
## Communication and Protocol
1. **Ethernet**: all Opta devices feature an onboard low-power 10BASE-T/100BASE-TX Ethernet physical Layer transciever. ```#include <Ethernet.h```

2. **RS-485**: Opta RS485 and Opta WIFI variants have a built-in RS-485 interface, which enables the construction of robus reliable data transmission systems. ```#include <ArduinoRS485.h>```
3. **Modbus TCP**: Opta RS485 and WiFi variants incorporate a built-in Modbus interface, which enables the implementation of robust and reliable data transmission systems. Modbus, in its RTU version that utilizes RS-485 serial transmission or its TCP version that operates over the Ethernet remains widely used protocols for industrial automation process.
	1. Modbus-RTU  operates in half-duplex mode, and is supported using Opta's RS-485 physical Interface.
	2. Opta does not have internal terminal resistors, so they must be specified added following the Modbus protocol specification.
	3. Modbus TCP takes advantage of Ethernet connectivity and allows easy integration with existing computer networks, and fascilitate data transmission over very long distancess. Also, it better than RTU version in that is operates in full-duplex mode.
4. **Wi-Fi**: Opta WiFi devices features an onboard WiFi module foor wireless connectivity. This can be accessed and set up using ```#include <WiFi.h>```. These devices also feature **Bluetooth** through _#include <ArduinoBLE.h>_.
5. **OPC UA**: This is industrial communication protocol widely used in IIoT systems. It is platform independent and very secure method for exchanging information between devices and systems. _open62541_ librarry is an open-source implementation of the OPC UA standard. ( It is efficient, and written in C, which is very suitable for embedded devices like Opta)
	1. The library  provides flexible architecture to create OPC UA clients and servers. This library can support upto two Opta Expansion Boads via OPC UA.(Will be very challenging to get them up and running)



# Getting started with Structured Text on Opta

- Structured Tex(ST) is part of IEC stanard that can be used to program the Opta PLC.
- With ST, complex and sophisticated programs can be created. 
- AI can easily be integrated with this language.
## Program 1:
	The first program will create a stop-stop circuit with two lighted pushbutotn switches using structured text programming. When green LED pushbutton is selected, the greenLED light will turn ON, remaining until the red led button is pressed, and son on.

### Step 1: Project Creation
Create a new project by opening the Arduino PLC IDE ( Not Arduino IDE).( This should be straight forward)
### Step 2: Mapping Physical I/O of Opta PLC

The Opta has physical inputs and outputs which must be mapped before they can be used in any project. These are located in  ```Resources```  tab, and are called ```Local IO Mapping```.
This will show all physical inputs and outputs of this controller.
By **IO Mapping**, we mean that we assign a variable to every physical IO that is intended to be used in the program.
-  Programmable Inputs can be selected as Analog or Digital(Default)
### Step 4: Wiring inputs and Outputs
simple based on tasks.
### Step 5: Tasks
 Taskes in Opta PLC can bre access under Project tabs. Opta has Four Tasks that run cyclically at different cycles. They can be configured as required by the end user.

### Step 6: Writing Program
- Create the actual program
-  Structured Text, must account for all variables, ther must be INIT program to initialize the variables. You
## Setup up the Network Connection for Arduino Opta
To set up the network connect and connect to opta using ModbucTCP (Ethernet), follow the following steps

**Step 1:** Put the Opta in boot mode, by double clicking the reset button.
**Step 2:** Connect the USB port (You will need to connect this because you can't use ModbusTCP at first startup)
**Step 3:** Edit the  Sketch in Arduino PLC IDE 1.0 to configure your network configuration (IP networks,and so on). Be sure that the Opta's is in the same subnet as the programming PC.
**Step 4:** Go ahead and download this configurations using the Modbus(USB).

The Opta will now be configure and be able to connect internet. Test connectivity with ping.

Step 5: To connect to opta with Ethernet, simple head to "On-Line"->"Set up Communication" -> then select "ModbusTCP" and activate it, setting the host ip to the actual opta's IP address you defined in step 3. Then click "connect" to connect.

IMPORTANT: Copy the Opta's Network configuration for use in future project.
In every project, first configure the network, and then load the code. (This is actually the case for each and every project for even the other PLCs, you must make sure the network config are consistent with the onece that are already)

Once connected, One can easily download PLC Code. by clicking "Download PLC code" button.


  