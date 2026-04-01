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

# Options and Secrets
OPTIONS_PATH = os.environ.get('OPTIONS_PATH', '/data/options.json')
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
OUTPUT_PATH = os.environ.get('OUTPUT_PATH', '/config/www/transit_billboard.bmp')
INPUT_PATH = None
ESP_UPDATE_SERVICE = ""
ws_connection = None

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
    global ENTITIES, ESP_UPDATE_SERVICE, INPUT_PATH
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, 'r') as f:
                opts = json.load(f)
                logging.info(f"Loaded options: {opts}")
                ENTITIES['K-Ingleside'] = opts.get('k_ingleside_sensor', ENTITIES['K-Ingleside'])
                ENTITIES['43-Masonic'] = opts.get('_43_masonic_sensor', ENTITIES['43-Masonic'])
                ENTITIES['23-Monterey'] = opts.get('_23_monterey_sensor', ENTITIES['23-Monterey'])
                ESP_UPDATE_SERVICE = opts.get('esp_update_service', "")
                
                bg_path = opts.get('background_image_path', '/config/www/background.bmp')
                if bg_path and os.path.exists(bg_path):
                    INPUT_PATH = bg_path
                else:
                    logging.warning(f"Background image not found at '{bg_path}', defaulting to internal path.")
                    INPUT_PATH = bg_path if bg_path else '/config/www/background.bmp'
        except Exception as e:
            logging.error(f"Error loading options.json: {e}")

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
        generate_billboard(current_data, INPUT_PATH if os.path.exists(INPUT_PATH or "") else None, OUTPUT_PATH)
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
    
    generate_billboard(current_data, INPUT_PATH if os.path.exists(INPUT_PATH or "") else None, OUTPUT_PATH)

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
                    
                    for route_name, track_id in ENTITIES.items():
                        if entity_id == track_id:
                            new_state = data.get("new_state", {}).get("state")
                            current_data[route_name] = parse_state(new_state)
                            
                            safe_input = INPUT_PATH if os.path.exists(INPUT_PATH or "") else None
                            generate_billboard(current_data, safe_input, OUTPUT_PATH)
                            await trigger_esp_update_if_needed()
                            break
                            
        except websockets.exceptions.ConnectionClosed:
            ws_connection = None
            await asyncio.sleep(5)
        except Exception as e:
            ws_connection = None
            await asyncio.sleep(5)

# --- Web UI (Ingress) Server ---

async def handle_index(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Transit Billboard</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; background: #111; color: #fff; }}
            .card {{ background: #222; padding: 20px; border-radius: 8px; max-width: 600px; margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }}
            .preview-container {{ display: flex; gap: 20px; justify-content: center; margin-top: 10px; }}
            .preview-box {{ text-align: center; }}
            .preview {{ border: 1px solid #444; image-rendering: pixelated; width: 256px; height: 128px; background: #000; }}
            input[type=file] {{ margin: 15px 0; background: #333; padding: 10px; border-radius: 4px; width: 100%; box-sizing: border-box; }}
            button {{ background: #03a9f4; color: white; border: none; padding: 12px 20px; border-radius: 4px; cursor: pointer; font-weight: bold; width: 100%; font-size: 16px; }}
            button:hover {{ background: #0288d1; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2 style="margin-top:0;">Transit Billboard Uploader</h2>
            <p>Upload a custom <b>64x32</b> <code>.bmp</code> file to use as the background layout for your display! Leave transparent pixels perfectly black (<code>#000000</code>) so they don't overwrite the generated ETA text.</p>
            <form action="upload" method="post" enctype="multipart/form-data">
                <input type="file" name="background" accept=".bmp" required>
                <button type="submit">Upload & Apply Background</button>
            </form>
            
            <hr style="border-color:#444; margin: 30px 0;">
            
            <div class="preview-container">
                <div class="preview-box">
                    <h3 style="font-size:14px; color:#aaa;">Raw Background</h3>
                    <img class="preview" src="preview_bg.bmp?t={int(time.time())}" alt="Background Preview">
                </div>
                <div class="preview-box">
                    <h3 style="font-size:14px; color:#aaa;">Live Matrix Preview</h3>
                    <img class="preview" src="preview_live.bmp?t={int(time.time())}" alt="Live Preview">
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def handle_upload(request):
    reader = await request.multipart()
    field = await reader.next()
    if field.name == 'background':
        filename = field.filename
        
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
        
        generate_billboard(current_data, target_path, OUTPUT_PATH)
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

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
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
