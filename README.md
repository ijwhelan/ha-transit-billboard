# Transit Billboard for Home Assistant and ESPHome

This project allows you to build a transit departures board using an ESP32 and a HUB75 display, orchestrated by a [Home Assistant](https://www.home-assistant.io/) server. 

<img width="500" alt="A HUB75 display in a 3D printed enclosure showing transit predictions for 3 transit lines." src="https://github.com/user-attachments/assets/5050894c-69f3-4fd7-aa13-15e92a37c6dc" /><br />

Your Home Assistant server aggregates transit data for the lines and stops you specify, and this data is baked into a bitmap which is then served to your ESP32. Transit data can be painted atop a custom background bitmap, with a web UI for configuring the following:
* Home Assistant entities corresponding to each transit line's prediction data
* X/Y placement of each line's prediction data on top of your background bitmap
* Maximum number of predictions to display per-line
* A lower bound filtering threshold to allow you to account for walking time to a given transit stop 

<img width="500" alt="A web UI running on Home Assistant for configuring the display of transit data on the end device." src="https://github.com/user-attachments/assets/a5fd3f44-7303-413f-b089-0e65cb498acf" /><br />

> **⚠️ AI Slop Disclosure**
> 
> At this point, this project contains predominantly LLM-generated code. I am comfortable running this on my Home Assistant server because I prompted and supervised the LLM, but you should exercise scrutiny of anything you're running on your local network.
> 
> **This documentation was entirely written by a human (me).**

## Getting Started
To use this project, you'll need the following:
* A Home Assistant server with:
  * The [ESPHome integration](https://www.home-assistant.io/integrations/esphome)
  * A transit data integration
    * I use the [bcpearce/homeassistant-gtfs-realtime](https://github.com/bcpearce/homeassistant-gtfs-realtime) integration, setup instructions are available in that repo.
* An ESP32 connected to a HUB75 display with an adequate power source.
  * **HUB75 displays draw a lot of power, do not power the display off of the ESP32!**
  * The [ESP32-Trinity](https://esp32trinity.com/) is a frequently-recommended turnkey solution that lets you plug an ESP32 directly into a HUB75 display and has provisions for properly powering the display.
    * NB: This project is not configured for the ESP32-Trinity by default, reference the [board presets](https://esphome.io/components/display/hub75/) available for this board and others to modify `billboard.yaml` for your use.
  * I've had success using these [USB-PD trigger boards](https://www.amazon.com/AITRIP-Charge-Adjustable-Voltage-Trigger/dp/B0D7942HWP/) to power the ESP32 and HUB75 display. I'd recommend bridging the 5V pads on the back of the board to lock it to 5V output so as not to release the magic smoke from your ESP32 and HUB75 display.
    * NB: These boards don't allow you to pass data through the USB-C connector. This isn't a huge deal for this project as ESPHome supports OTA updates. Once you perform the initial flash directly connected to the ESP32, you shouldn't need a direct USB data connection again.

### Home Assistant
* On your Home Assistant server, navigate to `Settings > Apps > Install app`.
* In the top right corner, select `Repositories` in the overflow menu:
  * <img width="174" height="192" alt="image" src="https://github.com/user-attachments/assets/ac51760f-6e02-4211-8038-5dc303bd033d" />
* Add this repository (https://github.com/ijwhelan/ha-transit-billboard)
* Return to the Home Assistant App Store and select `Check for updates` in the overflow menu:
  * <img width="172" height="193" alt="image" src="https://github.com/user-attachments/assets/a33c2571-5911-4b8f-a040-dbd81a9ebb47" />
* Search for `Transit Billboard Builder` and install the app.

### ESP32
* Ensure that you have `esphome` installed ([instructions](https://esphome.io/guides/installing_esphome/)).
* Clone this repo to your local machine.
* Navigate to the `esphome` directory.
* Create a `secrets.yaml` file to contain an OTA password for your device:
  * ```yaml
    billboard_ota_password: "YOUR PASSWORD HERE"
    ```
* Connect your ESP32 to your machine over USB.
* Flash your ESP32 using `esphome`: `esphome run billboard.yaml`
* Once your ESP32 has been flashed, wire the HUB75 input pins to the ESP32 GPIO pins as follows:
  * | HUB75 Input | ESP32 GPIO |
    |-------------|------------|
    | `R1` | `25` |
    | `G1` | `27` |
    | `B1` | `26` |
    | `R2` | `14` |
    | `G2` | `13` |
    | `B2` | `21` |
    | `A` | `23` |
    | `B` | `19` |
    | `C` | `22` |
    | `D` | `17` |
    | `E` | `32` |
    | `LAT` | `4` |
    | `OE` | `33` |
    | `CLK` | `18` |
  * This pinout was (relatively) convenient for my ESP32 board and mounting solution, these values can be changed in `billboard.yaml` to suit your needs. Look for the `display` tag in the file if you want to change these values.
    * Users of ESP32-Trinity or Adafruit MatrixPortal boards can use [board presets](https://esphome.io/components/display/hub75/) instead of defining each pin.
* Power up the device.
* The device broadcasts a captive portal wifi network for configuration, connect to it from a wifi-capable device to configure.
  * SSID: `Transit-Billboard`
  * Password: `ilovetrains`
* Connect the device to a wifi network that can access your Home Assistant server.
* On your Home Assistant server, verify that you can see the device (ensure you have the [ESPHome integration](https://www.home-assistant.io/integrations/esphome) enabled).
  * <img width="348" height="337" alt="image" src="https://github.com/user-attachments/assets/772a0a60-326b-4c1a-97c6-ea8a8c294af0" />

    

