import asyncio
import websockets
import json
import logging
import os
import time
import aiohttp
from ha_billboard import generate_billboard

logging.basicConfig(level=logging.INFO, format='%(message)s')

# Options and Secrets
OPTIONS_PATH = os.environ.get('OPTIONS_PATH', '/data/options.json')
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
OUTPUT_PATH = os.environ.get('OUTPUT_PATH', '/config/www/transit_billboard.bmp')
ESP_UPDATE_SERVICE = ""

# Default entities if options.json is missing or incomplete
ENTITIES = {
    'K-Ingleside': 'sensor.k_ingleside_arrivals',
    '43-Masonic': 'sensor.43_masonic_arrivals',
    '23-Monterey': 'sensor.23_monterey_arrivals'
}

current_data = {
    'K-Ingleside': [],
    '43-Masonic': [],
    '23-Monterey': []
}

def load_options():
    global ENTITIES, ESP_UPDATE_SERVICE
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, 'r') as f:
                opts = json.load(f)
                logging.info(f"Loaded options: {opts}")
                ENTITIES['K-Ingleside'] = opts.get('k_ingleside_sensor', ENTITIES['K-Ingleside'])
                ENTITIES['43-Masonic'] = opts.get('_43_masonic_sensor', ENTITIES['43-Masonic'])
                ENTITIES['23-Monterey'] = opts.get('_23_monterey_sensor', ENTITIES['23-Monterey'])
                ESP_UPDATE_SERVICE = opts.get('esp_update_service', "")
        except Exception as e:
            logging.error(f"Error loading options.json: {e}")

def parse_state(state_str):
    if not state_str or str(state_str).strip().lower() in ('unknown', 'unavailable', 'none', 'null', ''):
        return []
    # Depending on how the user's sensor formats the state, we extract integers.
    try:
        if isinstance(state_str, list):
            return state_str
        # Strip brackets if it was passed as string "[10, 15]"
        clean_str = str(state_str).replace('[', '').replace(']', '')
        return [int(float(x.strip())) for x in clean_str.split(',') if x.strip()]
    except Exception:
        # Fallback to string
        return [str(state_str)]

async def fetch_initial_states():
    if not SUPERVISOR_TOKEN:
        logging.warning("No SUPERVISOR_TOKEN found. Cannot fetch initial states.")
        # Generate empty billboard for testing
        generate_billboard(current_data, None, OUTPUT_PATH)
        return

    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "content-type": "application/json",
    }
    url_base = "http://supervisor/core/api/states/"

    async with aiohttp.ClientSession() as session:
        for route_name, entity_id in ENTITIES.items():
            if not entity_id:
                continue
            try:
                async with session.get(url_base + entity_id, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        state = data.get('state')
                        current_data[route_name] = parse_state(state)
            except Exception as e:
                logging.error(f"Error fetching {entity_id}: {e}")
    
    # Generate initial billboard
    logging.info(f"Initial states fetched: {current_data}")
    generate_billboard(current_data, None, OUTPUT_PATH)

async def listen():
    if not SUPERVISOR_TOKEN:
        logging.warning("No SUPERVISOR_TOKEN found. Running in dry mode.")
        while True: await asyncio.sleep(60)

    url = "ws://supervisor/core/websocket"
    
    async for websocket in websockets.connect(url):
        try:
            # Step 1: Tell HA who we are
            auth_msg = await websocket.recv()
            await websocket.send(json.dumps({
                "type": "auth",
                "access_token": SUPERVISOR_TOKEN
            }))
            
            auth_ok = await websocket.recv()
            auth_response = json.loads(auth_ok)
            if auth_response.get("type") != "auth_ok":
                logging.error(f"Authentication failed: {auth_response}")
                return
            
            logging.info("Authenticated successfully. Subscribing to state_changed events...")
            
            # Step 2: Subscribe to events
            req_id = 1
            await websocket.send(json.dumps({
                "id": req_id,
                "type": "subscribe_events",
                "event_type": "state_changed"
            }))
            
            sub_ok = await websocket.recv()
            logging.info("Subscription confirmed. Listening for updates...")
            
            # Loop forever processing events
            while True:
                msg_str = await websocket.recv()
                msg = json.loads(msg_str)
                
                if msg.get("type") == "event":
                    event = msg.get("event", {})
                    data = event.get("data", {})
                    entity_id = data.get("entity_id")
                    
                    # See if this entity matches any of our tracked entities
                    for route_name, track_id in ENTITIES.items():
                        if entity_id == track_id:
                            new_state = data.get("new_state", {}).get("state")
                            logging.info(f"{route_name} updated to: {new_state}")
                            
                            current_data[route_name] = parse_state(new_state)
                            generate_billboard(current_data, None, OUTPUT_PATH)
                            
                            if ESP_UPDATE_SERVICE and "." in ESP_UPDATE_SERVICE:
                                domain, service = ESP_UPDATE_SERVICE.split(".", 1)
                                try:
                                    await websocket.send(json.dumps({
                                        "id": int(time.time() * 1000),
                                        "type": "call_service",
                                        "domain": domain,
                                        "service": service,
                                        "service_data": {}
                                    }))
                                    logging.info(f"Triggered ESP update service: {ESP_UPDATE_SERVICE}")
                                except Exception as err:
                                    logging.error(f"Failed to trigger ESP update: {err}")
                            break
                            
        except websockets.exceptions.ConnectionClosed:
            logging.warning("WebSocket connection closed. Reconnecting...")
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            await asyncio.sleep(5)

async def main():
    load_options()
    await fetch_initial_states()
    await listen()

if __name__ == "__main__":
    asyncio.run(main())
