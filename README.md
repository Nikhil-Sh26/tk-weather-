# Water Weather

A refined Tkinter desktop weather app powered by OpenWeatherMap.

## Run

Open a terminal in this folder and run:

```bash
/Users/nikhil/.local/share/uv/python/cpython-3.11.17-macos-aarch64-none/bin/python3.11 main.py
```

**Do not use the system `python3` on this Mac.** `/usr/bin/python3` is linked
against Apple's retired Tk 8.5.9, which cannot draw the interface and shows an
empty window. The command above uses the uv-managed Python 3.11, which is built
against Tk 9.0 and renders correctly. Make sure a Python 3.10+ interpreter
built against Tk 8.6 or newer is used.

No third-party packages are required. The supplied `.env` contains your API key. Keep it private; do not commit or share this file.

## Features

- Live city search using OpenWeatherMap
- Responsive background requests so the interface never freezes
- Celsius/Fahrenheit switching
- A compact, live 12-hour outlook
- Saved places persisted locally in `settings.json`
- Friendly loading, empty-state, network, invalid-key, and city-not-found feedback
- Hydration and weather-aware water tips
