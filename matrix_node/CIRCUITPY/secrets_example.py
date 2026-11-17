# Copy the lines you need into secrets.py on the CIRCUITPY drive (keep your own
# ssid and password there). secrets.py never goes into the repo.
secrets = {
    "ssid": "HomeWiFi",                 # your WiFi name
    "password": "your-wifi-password",
    "timezone": "America/New_York",     # or "-07:00"; see chatty_clock.py for the names
    "latitude": 40.0,                   # optional: moonrise / moonset (stays on the board)
    "longitude": -100.0,
    "mqtt_hosts": "192.168.1.x",        # Chatty's home address (on Chatty: hostname -I)
    # "node_name": "matrix",
    # "twelve_hour": True,
    # "news_every": 20,                 # seconds of clock between news rounds
    # "night_start": 22, "night_end": 7,
}
