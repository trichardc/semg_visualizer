# Handles BLE communication with the COAPT EMGC Eval Kit

import asyncio
import time
import bleak


# TO IMPLEMENT AND DEBUG:
# 1) Hard timeout occuring even though heartbeats are being sent (serverside problem?)
# 2) Inconsistent heartbeat ID matches (sometimes matches, sometimes mismatch)
# 3) No way to kill program manually
# 4) Check that EMG values do seem reasonable and isn't just noise


DEVICE_NAME = 'CC0479' # Hard-coded for now; replace with input
CUSTOM_SERVICE_UUID = 'bd505a55-c892-4a2d-9fd0-4ed48997e555'
TX_CHARACTERISTIC_UUID = '799846a2-44c5-44ca-b620-41a48ac4459c'
RX_CHARACTERISTIC_UUID = 'd6b87f3a-2905-463f-8e5a-40d3dce8c186'

STOP_EVENT = asyncio.Event() # To force a hard stop to the program and disconnect

async def connect_to_device():
    """Scans for and connects to COAPT EMGC."""
    # Initialize selected device
    device = None 
    
    # Look for available devices
    found_devices = await bleak.BleakScanner.discover()
    for d in found_devices:
        if d.name == DEVICE_NAME:
            device = d
            break
    if device == None:
        print("No devices found.")
        return None

    # Connect with COAPT EMGC
    try:
        client = bleak.BleakClient(device.address)
        await client.connect()
        print(f"Connected to {device.name}.")
        return client
    except bleak.exc.BleakError as e:
        print(f"Connection failed: {e}.")
        return None

async def get_characteristics(client):
    """Gets TX/RX characteristics."""
    # Get services
    services = await client.get_services()
    custom_service = services.get_service(CUSTOM_SERVICE_UUID)

    # Get characteristics
    tx_characteristic = custom_service.get_characteristic(TX_CHARACTERISTIC_UUID)
    rx_characteristic = custom_service.get_characteristic(RX_CHARACTERISTIC_UUID)
    if tx_characteristic == None or rx_characteristic == None:
        print("TX or RX characteristic not found.")
        return None, None
    return tx_characteristic, rx_characteristic

def handle_tx_data(sender, data):
    parsed_data = parse_received_data(data)
    return None

def parse_received_data(data):
    """Parses received data. Only retrieves 0x01 and 0x04."""
    message_type = data[0]
    if message_type == 0x01:
        # Heartbeat response
        process_heartbeat_packet(data)
        return "Received heartbeat packet."
    elif message_type == 0x04:
        # EMG signal processing
        process_emg_signal(data)
        return "Received EMG signal features."
    else:
        return None

HEARTBEAT_ID = 0
LAST_HEARTBEAT_SENT_TIME = 0
HEARTBEAT_INTERVAL = 2
HEARTBEAT_TIMEOUT = 2
HARD_TIMEOUT = 5 # Fully stops streaming data if no heartbeat is exchanged
HEARTBEAT_EVENT = asyncio.Event() # Signals when a heartbeat has been received

async def send_heartbeat(client, rx_characteristic):
    """Sends a heartbeat packet to the server every HEARTBEAT_INTERVAL seconds."""
    global HEARTBEAT_ID
    global LAST_HEARTBEAT_SENT_TIME
    
    # Heartbeat loop
    while True:
        heartbeat_packet = construct_heartbeat_packet(HEARTBEAT_ID)
        try:
            await client.write_gatt_char(rx_characteristic, heartbeat_packet)
            print(f"Sent heartbeat (ID: {HEARTBEAT_ID}).")
            LAST_HEARTBEAT_SENT_TIME = time.time()
            HEARTBEAT_ID = (HEARTBEAT_ID + 1) % 256
        except bleak.exc.BleakError as e:
            print(f"Heartbeat send failed: {e}.")

        try:
            await asyncio.wait_for(HEARTBEAT_EVENT.wait(), timeout = HARD_TIMEOUT)
            HEARTBEAT_EVENT.clear()
            await asyncio.sleep(HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            print("Error: heartbeat hard timeout.")
            break
    STOP_EVENT.set()

def construct_heartbeat_packet(id):
    """Constructs a heartbeat packet."""
    packet = bytearray()
    packet.append(0x01)  # Type
    packet.append(id)  # ID
    packet.extend([0xFF, 0xFF, 0xFF])  # nzdata (three bytes of 0xFF)
    packet.append(0x0A)  # end
    return packet

def process_heartbeat_packet(data):
    """Parses and processes heartbeat packet."""
    global LAST_HEARTBEAT_SENT_TIME
    received_id = data[1]
    if received_id == HEARTBEAT_ID - 1:
        elapsed_time = time.time() - LAST_HEARTBEAT_SENT_TIME
        if elapsed_time <= HEARTBEAT_TIMEOUT:
            HEARTBEAT_EVENT.set()
            return None
        else:
            # Continue streaming data but print a warning
            print("Warning: heartbeat response timeout.")
            HEARTBEAT_EVENT.set()
            return None
    else:
        print(f"Error: Heartbeat ID mismatch (Received ID: {received_id})")
        HEARTBEAT_EVENT.set()
        return None

def process_emg_signal(data):
    def print_emg_signal(features):
        print(f"EMG signal features: {features}.")
        return None
    values = [data[i] for i in range(1, len(data))]
    print_emg_signal(values)
    return values

async def main():
    # Connect to device
    client = await connect_to_device()
    if client == None:
        return None
    
    # Get characteristics
    tx_char, rx_char = await get_characteristics(client)
    if tx_char is None:
        await client.disconnect()
        return None
    
    # Start retrieving data
    await client.start_notify(tx_char, handle_tx_data)

    # Separately, start heartbeat exchange
    asyncio.create_task(send_heartbeat(client, rx_char))

    # Keep program running
    await STOP_EVENT.wait()
    print("Disconnecting and killing the program.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())