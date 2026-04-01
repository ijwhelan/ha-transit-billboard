import sys
import json
from PIL import Image
import os

BITMAP_FONT = {
    '0': [
        " *** ",
        "*   *",
        "*   *",
        "*   *",
        "*   *",
        "*   *",
        " *** "
    ],
    '1': [
        " * ",
        "** ",
        " * ",
        " * ",
        " * ",
        " * ",
        "***"
    ],
    '2': [
        " *** ",
        "*   *",
        "    *",
        "   * ",
        "  *  ",
        " *   ",
        "*****"
    ],
    '3': [
        " *** ",
        "*   *",
        "    *",
        "  ** ",
        "    *",
        "*   *",
        " *** "
    ],
    '4': [
        "   * ",
        "  ** ",
        " * * ",
        "*  * ",
        "*****",
        "   * ",
        "   * "
    ],
    '5': [
        "*****",
        "*    ",
        "**** ",
        "    *",
        "    *",
        "*   *",
        " *** "
    ],
    '6': [
        " *** ",
        "*    ",
        "*    ",
        "**** ",
        "*   *",
        "*   *",
        " *** "
    ],
    '7': [
        "*****",
        "    *",
        "   * ",
        "  *  ",
        " *   ",
        "*    ",
        "*    "
    ],
    '8': [
        " *** ",
        "*   *",
        "*   *",
        " *** ",
        "*   *",
        "*   *",
        " *** "
    ],
    '9': [
        " *** ",
        "*   *",
        "*   *",
        " ****",
        "    *",
        "    *",
        " *** "
    ],
    ',': [
        "  ",
        "  ",
        "  ",
        "  ",
        "  ",
        "  ",
        " *",
        "* "
    ],
    ' ': [
        " ",
        " ",
        " ",
        " ",
        " ",
        " ",
        " "
    ]
}

def draw_text(image, x_start, y_start, text, color):
    x = x_start
    for char in text:
        if char not in BITMAP_FONT:
            continue
            
        bitmap = BITMAP_FONT[char]
        height = len(bitmap)
        width = len(bitmap[0])
            
        for row in range(height):
            for col in range(width):
                if bitmap[row][col] == '*':
                    if 0 <= (x + col) < 64 and 0 <= (y_start + row) < 32:
                        image.putpixel((x + col, y_start + row), color)
        
        # Move cursor right by character width + 1 pixel letter spacing
        x += width + 1

def generate_billboard(lines_config, input_path=None, output_path='/config/www/transit_billboard.bmp'):
    width, height = 64, 32
    
    # Load background image or fallback to black
    if input_path:
        try:
            bg_image = Image.open(input_path).convert('RGB')
            # Force resize to fit the 64x32 billboard perfectly
            image = bg_image.resize((width, height))
        except Exception as e:
            print(f"Could not load {input_path}, falling back to black background. Error: {e}")
            image = Image.new('RGB', (width, height), 'black')
    else:
        image = Image.new('RGB', (width, height), 'black')

    text_color = (255, 255, 255)  # White text
    accent_color = (255, 165, 0)  # Orange for the route number

    ###########################################################
    # PAINT YOUR ARRIVAL TIMES ON TOP OF YOUR BACKGROUND HERE #
    ###########################################################

    # lines_config is a list of dictionary objects: [{"name": "K", "x": 29, "y": 3, "arrivals": ["5", "12"]}]
    for line in lines_config:
        x_offset = int(line.get('x', 0))
        y_offset = int(line.get('y', 0))
        arrivals = line.get('arrivals', [])
        paint_arrival_times(image, x_offset, y_offset, arrivals, text_color)

    ############################
    # END CUSTOM PAINTING CODE #
    ############################    

    # Save the output image
    # Home Assistant doesn't always have a /config/www/ folder created by default.
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # Note: BMP is completely uncompressed and fast for ESP32 to draw
    image.save(output_path, format='BMP')
    print(f"Saved freshly baked billboard to {output_path}")

def paint_arrival_times(image, x_offset, y_offset, arrival_times, text_color):
    if len(arrival_times) > 0:
        clean_times = []
        for time in arrival_times:
            if str(time).strip().lower() in ("unknown", "unavailable", "none", "", "null"):
                continue
            try:
                # HA GTFS sensors often return floats (e.g. "10.798"). Round them cleanly to ints.
                clean_times.append(str(int(round(float(time)))))
            except (ValueError, TypeError):
                clean_times.append(str(time))
        
        if len(clean_times) == 0:
            return

        arrival_times_concatenated = ", ".join(clean_times)
        draw_text(image, x_offset, y_offset, arrival_times_concatenated, text_color)

if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            print("Usage: python3 ha_billboard.py <json_routes_data> [input_image_path] [output_path]")
            sys.exit(1)
        
        data_arg = sys.argv[1]
        lines_config = []
        
        try:
            lines_config = json.loads(data_arg)
        except json.JSONDecodeError:
            pass
        
        # Check for optional input image path
        in_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] not in ("", "None") else None
        # Check for optional output path
        out_path = sys.argv[3] if len(sys.argv) > 3 else '/config/www/transit_billboard.bmp'
        
        generate_billboard(lines_config, in_path, out_path)
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(script_dir, "billboard_log.txt")
        
        # Write success log for debugging in HA
        with open(log_path, 'w') as f:
            f.write(f"SUCCESS! Image successfully rendered and saved to: {out_path}\nData received: {data_arg}")
            
    except Exception as e:
        import traceback
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(script_dir, "billboard_log.txt")
        with open(log_path, 'w') as f:
            f.write(f"ERROR: {e}\n{traceback.format_exc()}\nArgs: {sys.argv}\n")
