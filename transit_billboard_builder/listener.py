import asyncio
import websockets
import json
import logging
import os
import time
import aiohttp
from aiohttp import web
from ha_billboard import generate_billboard

logging.basicConfig(level=logging.INFO, format='%(message)s')

# Secrets and paths
OPTIONS_PATH = os.environ.get('OPTIONS_PATH', '/data/options.json')
LINES_PATH = os.environ.get('LINES_PATH', '/data/lines.json')
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
OUTPUT_PATH = os.environ.get('OUTPUT_PATH', '/config/www/transit_billboard.bmp')
INPUT_PATH = None
ESP_UPDATE_SERVICE = ""
ws_connection = None

# Global state
lines_config = []
arrival_cache = {}

def load_options():
    global ESP_UPDATE_SERVICE, INPUT_PATH, lines_config
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, 'r') as f:
                opts = json.load(f)
                ESP_UPDATE_SERVICE = opts.get('esp_update_service', "")
                bg_path = opts.get('background_image_path', '/config/www/background.bmp')
                if bg_path and os.path.exists(bg_path):
                    INPUT_PATH = bg_path
                else:
                    INPUT_PATH = bg_path if bg_path else '/config/www/background.bmp'
        except Exception as e:
            logging.error(f"Error loading options.json: {e}")
            
    # Load dynamic lines config
    if os.path.exists(LINES_PATH):
        try:
            with open(LINES_PATH, 'r') as f:
                lines_config = json.load(f)
        except Exception as e:
            logging.error(f"Error loading lines.json: {e}")
    else:
        # Default fallback matching the original locations and lines so it seamlessly migrates users
        lines_config = [
            {"name": "K-Ingleside", "entity_id": "sensor.k_ingleside_arrivals", "x": 29, "y": 3},
            {"name": "43-Masonic", "entity_id": "sensor.43_masonic_arrivals", "x": 29, "y": 13},
            {"name": "23-Monterey", "entity_id": "sensor.23_monterey_arrivals", "x": 29, "y": 23}
        ]
        save_lines_config()

def save_lines_config():
    try:
        os.makedirs(os.path.dirname(LINES_PATH), exist_ok=True)
        with open(LINES_PATH, 'w') as f:
            json.dump(lines_config, f)
    except Exception as e:
        logging.error(f"Error saving lines.json: {e}")

def parse_state(state_str):
    if not state_str or str(state_str).strip().lower() in ('unknown', 'unavailable', 'none', 'null', ''):
        return []
    try:
        if isinstance(state_str, list):
            return state_str
        clean_str = str(state_str).replace('[', '').replace(']', '')
        return [int(float(x.strip())) for x in clean_str.split(',') if x.strip()]
    except Exception:
        return [str(state_str)]

def get_merged_lines():
    merged = []
    for line in lines_config:
        line_copy = dict(line)
        line_copy['arrivals'] = arrival_cache.get(line.get('entity_id'), [])
        merged.append(line_copy)
    return merged

def trigger_redraw():
    merged = get_merged_lines()
    safe_input = INPUT_PATH if (INPUT_PATH and os.path.exists(INPUT_PATH)) else None
    generate_billboard(merged, safe_input, OUTPUT_PATH)

async def trigger_esp_update_if_needed():
    global ws_connection
    if ESP_UPDATE_SERVICE and "." in ESP_UPDATE_SERVICE and ws_connection:
        domain, service = ESP_UPDATE_SERVICE.split(".", 1)
        try:
            await ws_connection.send(json.dumps({
                "id": int(time.time() * 1000),
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": {}
            }))
            logging.info(f"Triggered ESP update service: {ESP_UPDATE_SERVICE}")
        except Exception as err:
            logging.error(f"Failed to trigger ESP update: {err}")

async def fetch_initial_states():
    if not SUPERVISOR_TOKEN:
        logging.warning("No SUPERVISOR_TOKEN found. Cannot fetch initial states.")
        trigger_redraw()
        return

    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "content-type": "application/json",
    }
    url_base = "http://supervisor/core/api/states/"
    
    unique_entities = set(line.get('entity_id') for line in lines_config if line.get('entity_id'))

    async with aiohttp.ClientSession() as session:
        for entity_id in unique_entities:
            try:
                async with session.get(url_base + entity_id, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        state = data.get('state')
                        arrival_cache[entity_id] = parse_state(state)
            except Exception as e:
                logging.error(f"Error fetching {entity_id}: {e}")
    
    trigger_redraw()

async def listen():
    global ws_connection
    if not SUPERVISOR_TOKEN:
        logging.warning("No SUPERVISOR_TOKEN found. Running in dry mode.")
        while True: await asyncio.sleep(60)

    url = "ws://supervisor/core/websocket"
    
    async for websocket in websockets.connect(url):
        try:
            ws_connection = websocket
            auth_msg = await websocket.recv()
            await websocket.send(json.dumps({
                "type": "auth",
                "access_token": SUPERVISOR_TOKEN
            }))
            
            auth_ok = await websocket.recv()
            auth_response = json.loads(auth_ok)
            if auth_response.get("type") != "auth_ok":
                return
            
            req_id = 1
            await websocket.send(json.dumps({
                "id": req_id,
                "type": "subscribe_events",
                "event_type": "state_changed"
            }))
            
            sub_ok = await websocket.recv()
            
            while True:
                msg_str = await websocket.recv()
                msg = json.loads(msg_str)
                
                if msg.get("type") == "event":
                    event = msg.get("event", {})
                    data = event.get("data", {})
                    entity_id = data.get("entity_id")
                    
                    isTracked = False
                    for line in lines_config:
                        if line.get('entity_id') == entity_id:
                            isTracked = True
                            break
                            
                    if isTracked:
                        new_state = data.get("new_state", {}).get("state")
                        arrival_cache[entity_id] = parse_state(new_state)
                        
                        trigger_redraw()
                        await trigger_esp_update_if_needed()
                            
        except websockets.exceptions.ConnectionClosed:
            ws_connection = None
            await asyncio.sleep(5)
        except Exception as e:
            ws_connection = None
            await asyncio.sleep(5)

# --- Web UI (Ingress) Server ---

async def handle_index(request):
    # Depending on where the code executes, ingress.html is in / or current dir
    path = '/ingress.html' if os.path.exists('/ingress.html') else 'ingress.html'
    try:
        with open(path, 'r') as f:
            html = f.read()
            return web.Response(text=html, content_type='text/html')
    except Exception:
        return web.Response(text="ingress.html not found!", status=404)

async def handle_get_config(request):
    return web.json_response(lines_config)

async def handle_post_config(request):
    global lines_config
    try:
        new_config = await request.json()
        lines_config = new_config
        save_lines_config()
        
        # Redraw immediately
        trigger_redraw()
        await trigger_esp_update_if_needed()
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)

async def handle_upload(request):
    reader = await request.multipart()
    field = await reader.next()
    if field.name == 'background':
        target_path = INPUT_PATH if INPUT_PATH else '/config/www/background.bmp'
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        
        size = 0
        with open(target_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
        
        logging.info(f"Uploaded new background to {target_path} ({size} bytes)")
        trigger_redraw()
        await trigger_esp_update_if_needed()
        
    return web.HTTPFound(location='./')

async def handle_preview_bg(request):
    target_path = INPUT_PATH if INPUT_PATH and os.path.exists(INPUT_PATH) else None
    if target_path and os.path.exists(target_path):
        return web.FileResponse(target_path)
    return web.Response(status=404, text="No background currently set")

async def handle_preview_live(request):
    if os.path.exists(OUTPUT_PATH):
        return web.FileResponse(OUTPUT_PATH)
    return web.Response(status=404, text="No live output generated yet")

async def handle_get_entities(request):
    if not SUPERVISOR_TOKEN:
        return web.json_response([])
        
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "content-type": "application/json",
    }
    url = "http://supervisor/core/api/states"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Filter to just sensor entities or allow all? Let's return all entity_ids for flexibility
                    entities = [state.get("entity_id") for state in data if "entity_id" in state]
                    return web.json_response(entities)
    except Exception as e:
        logging.error(f"Error fetching entities list: {e}")
        
    return web.json_response([])

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
        web.get('/api/config', handle_get_config),
        web.get('/api/entities', handle_get_entities),
        web.post('/api/config', handle_post_config),
        web.post('/upload', handle_upload),
        web.get('/preview_bg.bmp', handle_preview_bg),
        web.get('/preview_live.bmp', handle_preview_live)
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8099)
    await site.start()

async def main():
    load_options()
    await start_web_server()
    await fetch_initial_states()
    await listen()

if __name__ == "__main__":
    asyncio.run(main())
