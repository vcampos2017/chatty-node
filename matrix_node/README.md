# Matrix node (Adafruit Matrix Portal M4 + 64x32 RGB panel)

A moon clock that is also a node on Chatty's network.

- **Home screen:** time, date, the moon's picture and how much is lit, and when it next
  rises or sets (Phil Burgess's Moon Phase Clock layout). The moon is now worked out on
  the board (`chatty_moon.py`): no web service, and the location never leaves the board.
- **News cards** every 20 seconds, from Chatty's MQTT board: weather alerts (scrolling),
  a lightning strike (miles, minutes ago), rain now (and the total) or rain coming (chance
  and hour), the greenhouse (temperature, dry / ok / wet), and nodes online ("3/4", plus
  the first quiet one).
- **Tornado Warning:** the whole panel turns into a blinking red TAKE COVER sign with the
  end time scrolling, at full brightness, until Chatty's alert list drops it.
- **Lightning** flashes the panel; **rain** makes blue drops fall over the moon.
- **Night** (22:00 to 7:00): the text dims.
- **Buttons:** UP = next card now, DOWN = back to the clock (no cards for 2 minutes).
- **On the network:** heartbeat `chatty/nodes/matrix/status` every minute (last will
  "offline"), the moon on `chatty/nodes/matrix/data`, both retained. Read-only: it never
  sends anyone a command.

Finding Chatty: the board can't use Tailscale or `chatty-node.local`, so it tries the
address that worked last time, her home addresses from her `chatty/hub` note (kept in the
board's small memory), then `mqtt_hosts` from secrets.py, then `chatty-node`.

## Files (copy everything in `CIRCUITPY/` to the drive)

| file | what |
| --- | --- |
| `code.py` | starts it |
| `chatty_matrix.py` | the app: schedule, buttons, heartbeat |
| `chatty_screen.py` | the clock layout, cards, tornado frame, flash, rain |
| `chatty_net.py` | WiFi (ESP32) and MQTT, old or new Adafruit libraries |
| `chatty_news.py` | MQTT news -> cards (tested on a computer) |
| `chatty_moon.py` | moon phase, moonrise, moonset (tested) |
| `chatty_clock.py` | time zones and daylight saving (tested) |
| `chatty_hub.py` | finding Chatty's board (tested) |
| `chatty_art.py` | the 9x9 card pictures |
| `secrets_example.py` | the settings to add to your secrets.py |

The board keeps its own `fonts/` and `moon/` folders from the Moon Phase Clock. The
original's startup splash images are not used. Libraries from the Adafruit bundle that
matches the board's CircuitPython: `adafruit_minimqtt`, `adafruit_connection_manager`,
`adafruit_ticks`, `adafruit_esp32spi`, `adafruit_requests`, `adafruit_display_text`,
`adafruit_bitmap_font`, `adafruit_lis3dh`, `adafruit_matrixportal`, `adafruit_portalbase`,
`adafruit_bus_device`, `neopixel`.

## On a computer

    python3 tests/test_matrix_node.py                         # runs it on stand-ins
    python3 scripts/preview_matrix.py out [fonts_dir]         # pictures of the panel

`sim/fake_circuitpython.py` holds the stand-ins (not for the board).

Moon Phase Clock by Phil 'PaintYourDragon' Burgess for Adafruit Industries, MIT license.
