"""Water Weather — a glassmorphism desktop weather companion built with Tkinter.

Set OPENWEATHER_API_KEY in your environment, or put it in a .env file beside
this program.  The app uses OpenWeatherMap's current weather endpoint.

The whole interface is drawn on a single Tk canvas (gradient, glow blobs,
frosted cards and vector icons) so it stays consistent on older Tk builds
where native widgets ignore custom colours.
"""

from __future__ import annotations

import json
import math
import os
import threading

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings.json"
ENV_PATH = APP_DIR / ".env"
API_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

FONT = "Helvetica Neue"
WHITE = "#FFFFFF"
MUTED = "#B9C7E6"
SUBTLE = "#8FA1C9"
ACCENT = "#7FE3FF"
DANGER = "#FF9AA6"
GRADIENT_BASE = "#0F1B3D"

# Background gradient stops, top -> bottom.
GRADIENT = [
    (0.00, "#0B1030"),
    (0.32, "#16224E"),
    (0.64, "#2A2A72"),
    (1.00, "#0D3B5C"),
]

# Soft colour blobs that sit behind the glass for the frosted effect.
BLOBS = [
    (0.80, 0.10, 0.46, "#6C4BFF", 0.55),
    (0.14, 0.28, 0.40, "#00B4FF", 0.42),
    (0.64, 0.88, 0.48, "#FF4FA3", 0.36),
    (0.28, 0.70, 0.34, "#00E0C6", 0.30),
]

GLASS_ALPHA = 0.14
GLASS_BORDER_ALPHA = 0.30


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def blend(color_a: str, color_b: str, t: float) -> str:
    """Mix two hex colours; t=0 returns color_a, t=1 returns color_b."""
    a, b = _hex_to_rgb(color_a), _hex_to_rgb(color_b)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def gradient_color(t: float) -> str:
    """Sample the background gradient at position t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    for i in range(len(GRADIENT) - 1):
        p0, c0 = GRADIENT[i]
        p1, c1 = GRADIENT[i + 1]
        if t <= p1:
            return blend(c0, c1, (t - p0) / (p1 - p0))
    return GRADIENT[-1][1]


def load_dotenv() -> None:
    """Load a small local .env file without an extra dependency."""
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class WaterWeather(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        self.api_key = os.environ.get("OPENWEATHER_API_KEY", "").strip()
        settings = self._load_settings()
        self.unit = settings.get("unit", "metric")
        self.favorites = settings.get("favorites", [])
        self.last_city = settings.get("last_city", "Mumbai, IN")

        self.current_city = ""
        self.timezone_offset = 0
        self.data = None
        self.forecast: dict = {"list": []}
        self.status_text = "Ready — search a city to begin"
        self.status_kind = "info"

        self.title("Water Weather")
        self.geometry("1120x800")
        self.minsize(980, 720)
        self.configure(bg=GRADIENT[0][1])

        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=GRADIENT[0][1])
        self.canvas.pack(fill="both", expand=True)

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            self.canvas, textvariable=self.search_var, relief="flat", bd=0,
            highlightthickness=0, justify="left", font=(FONT, 13),
        )
        self.search_entry.bind("<Return>", lambda _event: self.search_city())

        self._resize_job = None
        self.canvas.bind("<Configure>", self._on_resize)
        self.render()
        self.after(200, lambda: self.search_city(self.last_city))

    # ------------------------------------------------------------------ state

    def _load_settings(self) -> dict:
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        data = {"unit": self.unit, "favorites": self.favorites, "last_city": self.current_city or self.last_city}
        try:
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    # -------------------------------------------------------------- rendering

    def render(self) -> None:
        cv = self.canvas
        cv.config(cursor="")
        cv.delete("ui")
        width = cv.winfo_width()
        height = cv.winfo_height()
        if width <= 1 or height <= 1:
            width, height = 1120, 800
        self.width, self.height = width, height

        self._draw_background(width, height)
        self._draw_header(width, height)
        self._draw_search(width, height)
        self._draw_main_card(width, height)
        self._draw_glance(width, height)
        self._draw_saved(width, height)
        self._draw_status(width, height)
        self._place_entry(width, height)

    def _on_resize(self, _event) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._do_resize)

    def _do_resize(self) -> None:
        self._resize_job = None
        self.render()

    def _draw_background(self, width: int, height: int) -> None:
        cv = self.canvas
        step = 3
        for y in range(0, height, step):
            cv.create_rectangle(0, y, width, y + step, fill=gradient_color(y / height),
                                outline="", tags="ui")
        for rx, ry, rr, color, peak in BLOBS:
            cx, cy = rx * width, ry * height
            radius = rr * max(width, height) * 0.5
            base = gradient_color(cy / height)
            steps = 16
            for i in range(steps, 0, -1):
                frac = i / steps
                col = blend(base, color, peak * (1 - frac))
                r = radius * frac
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="", tags="ui")

    def _draw_header(self, width: int, height: int) -> None:
        cv = self.canvas
        m = self._margin()
        cv.create_text(m, 44, text="\u25c8  WATER WEATHER", anchor="w", fill=WHITE,
                       font=(FONT, 17, "bold"), tags="ui")
        cv.create_text(m, 70, text="Weather that flows with your day", anchor="w",
                       fill=MUTED, font=(FONT, 11), tags="ui")
        label = "\u00b0C" if self.unit == "metric" else "\u00b0F"
        self._pill(width - m - 96, 26, width - m, 62, label, self.toggle_unit)

    def _draw_search(self, width: int, height: int) -> None:
        cv = self.canvas
        m = self._margin()
        x0, x1 = m, width - m
        y0, y1 = 96, 148
        button_w = 132
        bar_x1 = x1 - button_w - 12

        base = gradient_color(((y0 + y1) / 2) / height)
        bar_fill = blend(base, WHITE, 0.80)
        self._round_rect(x0, y0, bar_x1, y1, (y1 - y0) / 2, fill=bar_fill,
                         outline=blend(base, WHITE, 0.55), width=1)
        self._bar_fill = bar_fill
        self._search_entry_bounds = (x0 + 22, y0 + 11, bar_x1 - 18, 30)

        self._pill(bar_x1 + 12, y0, x1, y1, "Search", self.search_city,
                   fill=blend("#38D0F5", WHITE, 0.03), text_fill="#04202C",
                   hover=blend("#38D0F5", WHITE, 0.35), font=(FONT, 12, "bold"))

    def _place_entry(self, width: int, height: int) -> None:
        x, y, w, h = self._search_entry_bounds
        self.search_entry.configure(bg=self._bar_fill, fg="#0A1730", insertbackground="#0A1730")
        self.search_entry.place(x=x, y=y, width=w, height=h)

    def _draw_main_card(self, width: int, height: int) -> None:
        cv = self.canvas
        m = self._margin()
        left_w = int((width - 2 * m - 18) * 0.61)
        x0, x1 = m, m + left_w
        y0, y1 = 172, height - m
        self._glass_card(x0, y0, x1, y1)

        values = self._display_values()
        pad = 30
        tint = 1.0 if self.data else 0.5

        cv.create_text(x0 + pad, y0 + pad, text=values["city"], anchor="nw", fill=WHITE,
                       font=(FONT, 26, "bold"), tags="ui")
        cv.create_text(x0 + pad, y0 + pad + 42, text=values["when"], anchor="nw", fill=MUTED,
                       font=(FONT, 11), tags="ui")

        hero_cy = y0 + 205
        self._draw_icon(x0 + pad + 72, hero_cy, 132, values["code"], tint)
        cv.create_text(x0 + pad + 172, hero_cy - 26, text=values["temp"], anchor="w", fill=WHITE,
                       font=(FONT, 60, "bold"), tags="ui")
        cv.create_text(x0 + pad + 178, hero_cy + 40, text=values["condition"], anchor="w",
                       fill=MUTED, font=(FONT, 14), tags="ui")

        inner_x0, inner_x1 = x0 + pad, x1 - pad
        gap = 12
        cw = (inner_x1 - inner_x0 - gap * 3) / 4

        chip_y0, chip_y1 = y0 + 300, y0 + 382
        stats = (("FEELS LIKE", values["feels"]), ("HUMIDITY", values["humidity"]),
                 ("WIND", values["wind"]), ("PRESSURE", values["pressure"]))
        for index, (heading, value) in enumerate(stats):
            a = inner_x0 + index * (cw + gap)
            self._glass_chip(a, chip_y0, a + cw, chip_y1)
            cv.create_text(a + 16, chip_y0 + 18, text=heading, anchor="nw", fill=SUBTLE,
                           font=(FONT, 8, "bold"), tags="ui")
            cv.create_text(a + 16, chip_y0 + 38, text=value, anchor="nw", fill=WHITE,
                           font=(FONT, 16, "bold"), tags="ui")

        cv.create_text(x0 + pad, y0 + 408, text=values["tip"], anchor="nw", fill=ACCENT,
                       font=(FONT, 12, "bold"), width=inner_x1 - inner_x0, justify="left", tags="ui")

        cv.create_text(x0 + pad, y0 + 468, text="NEXT 12 HOURS", anchor="nw", fill=ACCENT,
                       font=(FONT, 10, "bold"), tags="ui")
        hour_y0, hour_y1 = y0 + 492, y1 - 24
        for index in range(4):
            a = inner_x0 + index * (cw + gap)
            b = a + cw
            self._glass_chip(a, hour_y0, b, hour_y1, radius=16)
            centre = (a + b) / 2
            if index < len(values["hourly"]):
                hour = values["hourly"][index]
                cv.create_text(centre, hour_y0 + 18, text=hour["when"], anchor="center",
                               fill=SUBTLE, font=(FONT, 9, "bold"), tags="ui")
                self._draw_icon(centre, (hour_y0 + hour_y1) / 2 + 2, min(cw * 0.52, 48), hour["code"])
                cv.create_text(centre, hour_y1 - 20, text=hour["temp"], anchor="center",
                               fill=WHITE, font=(FONT, 13, "bold"), tags="ui")
            else:
                cv.create_text(centre, hour_y0 + 18, text="\u2014", anchor="center",
                               fill=SUBTLE, font=(FONT, 9, "bold"), tags="ui")
                cv.create_text(centre, (hour_y0 + hour_y1) / 2, text="\u00b7", anchor="center",
                               fill=SUBTLE, font=(FONT, 20), tags="ui")
                cv.create_text(centre, hour_y1 - 20, text="\u2014\u00b0", anchor="center",
                               fill=WHITE, font=(FONT, 13, "bold"), tags="ui")

    def _draw_glance(self, width: int, height: int) -> None:
        cv = self.canvas
        m = self._margin()
        left_w = int((width - 2 * m - 18) * 0.61)
        x0 = m + left_w + 18
        x1 = width - m
        y0, y1 = 172, 348
        self._glass_card(x0, y0, x1, y1)

        values = self._display_values()
        pad = 24
        cv.create_text(x0 + pad, y0 + pad, text="TODAY AT A GLANCE", anchor="nw", fill=ACCENT,
                       font=(FONT, 10, "bold"), tags="ui")
        cv.create_text(x0 + pad, y0 + 58, text=f"High {values['high']}    \u2022    Low {values['low']}",
                       anchor="nw", fill=WHITE, font=(FONT, 19, "bold"), tags="ui")
        cv.create_text(x0 + pad, y0 + 100, text=f"Sunrise  {values['sunrise']}", anchor="nw",
                       fill=MUTED, font=(FONT, 11), tags="ui")
        cv.create_text(x0 + pad, y0 + 124, text=f"Sunset  {values['sunset']}", anchor="nw",
                       fill=MUTED, font=(FONT, 11), tags="ui")
        cv.create_text(x1 - pad, y1 - pad, text="LIVE \u2022 OPENWEATHER", anchor="se",
                       fill=SUBTLE, font=(FONT, 8, "bold"), tags="ui")

    def _draw_saved(self, width: int, height: int) -> None:
        cv = self.canvas
        m = self._margin()
        left_w = int((width - 2 * m - 18) * 0.61)
        x0 = m + left_w + 18
        x1 = width - m
        y0, y1 = 364, height - m
        self._glass_card(x0, y0, x1, y1)

        pad = 24
        cv.create_text(x0 + pad, y0 + pad, text="SAVED PLACES", anchor="nw", fill=ACCENT,
                       font=(FONT, 10, "bold"), tags="ui")
        self._pill(x1 - pad - 84, y0 + pad - 7, x1 - pad, y0 + pad + 21, "+ Save",
                   self.save_current, font=(FONT, 10, "bold"))

        if not self.favorites:
            cv.create_text(x0 + pad, y0 + 66, text="Save a city for one-click weather checks.",
                           anchor="nw", fill=MUTED, font=(FONT, 10), width=(x1 - x0) - 2 * pad,
                           justify="left", tags="ui")
            return

        row_y = y0 + 66
        row_h = 34
        for city in self.favorites[:8]:
            if row_y + row_h > y1 - 16:
                break
            self._glass_chip(x0 + pad, row_y, x1 - pad, row_y + row_h, radius=10)
            self._text_button(x0 + pad + 14, row_y + row_h / 2, city,
                              lambda c=city: self.search_city(c), anchor="w",
                              font=(FONT, 11, "bold"))
            self._text_button(x1 - pad - 16, row_y + row_h / 2, "\u00d7",
                              lambda c=city: self.remove_favorite(c), anchor="e",
                              font=(FONT, 14), fill=MUTED, hover=DANGER)
            row_y += row_h + 8

    def _draw_status(self, width: int, height: int) -> None:
        colors = {"info": MUTED, "ok": ACCENT, "error": DANGER}
        self.canvas.create_text(self._margin(), 160, text=f"\u25cf  {self.status_text}", anchor="w",
                                fill=colors.get(self.status_kind, MUTED), font=(FONT, 10), tags="ui")

    # ----------------------------------------------------------- drawing tools

    def _margin(self) -> int:
        return 40

    def _round_rect(self, x0, y0, x1, y1, r, **kwargs):
        r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        points = [
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
        ]
        kwargs.setdefault("tags", "ui")
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _glass_card(self, x0, y0, x1, y1, radius=22):
        base = gradient_color(((y0 + y1) / 2) / self.height)
        return self._round_rect(
            x0, y0, x1, y1, radius,
            fill=blend(base, WHITE, GLASS_ALPHA),
            outline=blend(base, WHITE, GLASS_BORDER_ALPHA), width=1,
        )

    def _glass_chip(self, x0, y0, x1, y1, radius=16):
        base = gradient_color(((y0 + y1) / 2) / self.height)
        return self._round_rect(
            x0, y0, x1, y1, radius,
            fill=blend(base, WHITE, GLASS_ALPHA + 0.07),
            outline=blend(base, WHITE, GLASS_BORDER_ALPHA + 0.08), width=1,
        )

    def _pill(self, x0, y0, x1, y1, text, command, *, fill=None, text_fill=WHITE,
              hover=None, font=None):
        cv = self.canvas
        if fill is None:
            base = gradient_color(((y0 + y1) / 2) / self.height)
            fill = blend(base, WHITE, 0.22)
            border = blend(base, WHITE, 0.38)
        else:
            border = ""
        hover = hover or blend(fill, WHITE, 0.18)
        rect = self._round_rect(x0, y0, x1, y1, (y1 - y0) / 2, fill=fill, outline=border, width=1)
        label = cv.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text, fill=text_fill,
                               font=font or (FONT, 11, "bold"), tags="ui")
        for item in (rect, label):
            cv.tag_bind(item, "<Button-1>", lambda _e: command())
            cv.tag_bind(item, "<Enter>", lambda _e: (cv.itemconfig(rect, fill=hover),
                                                     cv.config(cursor="hand2")))
            cv.tag_bind(item, "<Leave>", lambda _e: (cv.itemconfig(rect, fill=fill),
                                                     cv.config(cursor="")))
        return rect

    def _text_button(self, x, y, text, command, *, anchor="w", font=None,
                     fill=WHITE, hover=ACCENT):
        cv = self.canvas
        item = cv.create_text(x, y, text=text, anchor=anchor, fill=fill,
                              font=font or (FONT, 11), tags="ui")
        cv.tag_bind(item, "<Button-1>", lambda _e: command())
        cv.tag_bind(item, "<Enter>", lambda _e: (cv.itemconfig(item, fill=hover),
                                                 cv.config(cursor="hand2")))
        cv.tag_bind(item, "<Leave>", lambda _e: (cv.itemconfig(item, fill=fill),
                                                 cv.config(cursor="")))
        return item

    # ------------------------------------------------------------- weather art

    @staticmethod
    def _icon_kind(code):
        if code is None:
            return "cloud"
        if 200 <= code < 300:
            return "storm"
        if 300 <= code < 600:
            return "rain"
        if 600 <= code < 700:
            return "snow"
        if 700 <= code < 800:
            return "mist"
        if code == 800:
            return "sun"
        if code in (801, 802):
            return "partly"
        return "cloud"

    def _tint(self, color: str, tint: float) -> str:
        return color if tint >= 1.0 else blend(GRADIENT_BASE, color, tint)

    def _draw_icon(self, cx, cy, size, code, tint=1.0) -> None:
        kind = self._icon_kind(code)
        if kind == "sun":
            self._draw_sun(cx, cy, size, tint)
        elif kind == "partly":
            self._draw_sun(cx - size * 0.20, cy - size * 0.18, size * 0.72, tint)
            self._draw_cloud(cx, cy + size * 0.10, size * 0.92, tint)
        elif kind == "rain":
            self._draw_cloud(cx, cy - size * 0.16, size * 0.92, tint)
            self._draw_rain(cx, cy + size * 0.20, size, tint)
        elif kind == "storm":
            self._draw_cloud(cx, cy - size * 0.16, size * 0.92, tint)
            self._draw_bolt(cx, cy + size * 0.16, size, tint)
        elif kind == "snow":
            self._draw_cloud(cx, cy - size * 0.16, size * 0.92, tint)
            self._draw_snow(cx, cy + size * 0.24, size, tint)
        elif kind == "mist":
            self._draw_cloud(cx, cy - size * 0.18, size * 0.92, tint)
            self._draw_mist(cx, cy + size * 0.20, size, tint)
        else:
            self._draw_cloud(cx, cy, size, tint)

    def _draw_sun(self, cx, cy, size, tint=1.0):
        cv = self.canvas
        radius = size * 0.22
        ray = self._tint("#FFD873", tint)
        for i in range(8):
            angle = math.radians(i * 45)
            cv.create_line(
                cx + math.cos(angle) * radius * 1.5, cy + math.sin(angle) * radius * 1.5,
                cx + math.cos(angle) * radius * 2.0, cy + math.sin(angle) * radius * 2.0,
                fill=ray, width=max(2, size * 0.045), capstyle="round", tags="ui",
            )
        cv.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                       fill=self._tint("#FFD873", tint), outline=self._tint("#FFF0BE", tint),
                       width=2, tags="ui")

    def _draw_cloud(self, cx, cy, size, tint=1.0):
        cv = self.canvas
        fill = self._tint("#E9F2FC", tint)
        self._round_rect(cx - 0.40 * size, cy - 0.02 * size, cx + 0.40 * size, cy + 0.20 * size,
                         0.09 * size, fill=fill, outline="")
        for ox, oy, r in ((-0.24, -0.02, 0.18), (0.0, -0.14, 0.23), (0.22, 0.0, 0.17)):
            cv.create_oval(cx + (ox - r) * size, cy + (oy - r) * size,
                           cx + (ox + r) * size, cy + (oy + r) * size,
                           fill=fill, outline="", tags="ui")

    def _draw_rain(self, cx, cy, size, tint=1.0):
        cv = self.canvas
        col = self._tint("#8FD8FF", tint)
        for ox in (-0.24, 0.0, 0.24):
            x = cx + ox * size
            cv.create_line(x + 0.06 * size, cy - 0.04 * size, x - 0.02 * size, cy + 0.14 * size,
                           fill=col, width=max(2, size * 0.05), capstyle="round", tags="ui")

    def _draw_bolt(self, cx, cy, size, tint=1.0):
        s = size
        points = [
            cx, cy - 0.14 * s, cx + 0.13 * s, cy - 0.14 * s, cx + 0.01 * s, cy + 0.02 * s,
            cx + 0.12 * s, cy + 0.02 * s, cx - 0.08 * s, cy + 0.28 * s, cx - 0.01 * s, cy + 0.07 * s,
            cx - 0.12 * s, cy + 0.07 * s,
        ]
        self.canvas.create_polygon(points, fill=self._tint("#FFD35C", tint), outline="", tags="ui")

    def _draw_snow(self, cx, cy, size, tint=1.0):
        cv = self.canvas
        col = self._tint("#DCEBFF", tint)
        for ox in (-0.22, 0.0, 0.22):
            x = cx + ox * size
            for angle in range(0, 360, 60):
                rad = math.radians(angle)
                cv.create_line(x, cy, x + math.cos(rad) * size * 0.075,
                               cy + math.sin(rad) * size * 0.075,
                               fill=col, width=2, capstyle="round", tags="ui")

    def _draw_mist(self, cx, cy, size, tint=1.0):
        cv = self.canvas
        col = self._tint("#CDE3F5", tint)
        for i, w in enumerate((0.62, 0.50, 0.58)):
            y = cy + i * size * 0.11
            cv.create_line(cx - w * size / 2, y, cx + w * size / 2, y,
                           fill=col, width=max(2, size * 0.05), capstyle="round", tags="ui")

    # ------------------------------------------------------------------- data

    def _display_values(self) -> dict:
        data = self.data
        if not data:
            return {
                "city": "Search a city", "when": "Enter a city to see live weather",
                "temp": "\u2014\u00b0", "condition": "Waiting for weather", "code": None,
                "feels": "\u2014", "humidity": "\u2014", "wind": "\u2014", "pressure": "\u2014",
                "high": "\u2014", "low": "\u2014", "sunrise": "\u2014", "sunset": "\u2014",
                "tip": "Water-wise tips will appear here once a city is loaded.", "hourly": [],
            }

        main = data["main"]
        weather = data["weather"][0]
        wind = data.get("wind", {})
        sys = data.get("sys", {})
        degree = "\u00b0C" if self.unit == "metric" else "\u00b0F"
        speed = "km/h" if self.unit == "metric" else "mph"
        wind_value = wind.get("speed", 0) * 3.6 if self.unit == "metric" else wind.get("speed", 0)

        hourly = []
        for entry in self.forecast.get("list", [])[:4]:
            local = datetime.fromtimestamp(entry["dt"] + self.timezone_offset, timezone.utc)
            hourly.append({
                "when": "Now" if not hourly else local.strftime("%I %p").lstrip("0"),
                "code": entry["weather"][0]["id"],
                "temp": f"{round(entry['main']['temp'])}\u00b0",
            })

        return {
            "city": self.current_city,
            "when": f"Updated {datetime.now().strftime('%I:%M %p')}  \u2022  Live conditions",
            "temp": f"{round(main['temp'])}\u00b0",
            "condition": weather["description"].title(),
            "code": weather["id"],
            "feels": f"{round(main['feels_like'])}{degree}",
            "humidity": f"{main['humidity']}%",
            "wind": f"{wind_value:.0f} {speed}",
            "pressure": f"{main['pressure']} hPa",
            "high": f"{round(main['temp_max'])}{degree}",
            "low": f"{round(main['temp_min'])}{degree}",
            "sunrise": self._clock(sys.get("sunrise")),
            "sunset": self._clock(sys.get("sunset")),
            "tip": self._water_tip(main["temp"], main["humidity"], weather["id"]),
            "hourly": hourly,
        }

    def _clock(self, timestamp) -> str:
        if not timestamp:
            return "\u2014"
        return datetime.fromtimestamp(timestamp + self.timezone_offset, timezone.utc).strftime("%I:%M %p")

    def _water_tip(self, temp: float, humidity: int, code: int) -> str:
        if code < 600:
            return "\u2602 Rainy conditions: carry a reusable bottle and let nature handle the watering."
        if temp >= (30 if self.unit == "metric" else 86):
            return "\U0001F4A7 It's warm: drink water regularly and water plants early or late in the day."
        if humidity < 35:
            return "\U0001F4A7 Dry air today: keep a water bottle nearby and check thirsty plants."
        return "\U0001F4A7 A comfortable day to stay hydrated \u2014 small, regular sips work best."

    # --------------------------------------------------------------- behaviour

    def search_city(self, city=None) -> None:
        city = (city if city is not None else self.search_var.get()).strip()
        if not city:
            self.status_text = "Enter a city name to search."
            self.status_kind = "error"
            self.render()
            self.search_entry.focus_set()
            return
        if not self.api_key:
            self.status_text = "API key not configured."
            self.status_kind = "error"
            self.render()
            messagebox.showinfo("API key needed",
                                "Create a .env file beside main.py with:\n\nOPENWEATHER_API_KEY=your_key")
            return
        self.search_var.set(city)
        self.status_text = f"Fetching live weather for {city}\u2026"
        self.status_kind = "info"
        self.render()
        threading.Thread(target=self._fetch_weather, args=(city,), daemon=True).start()

    def _fetch_weather(self, city: str) -> None:
        params = urlencode({"q": city, "appid": self.api_key, "units": self.unit})
        try:
            with urlopen(f"{API_URL}?{params}", timeout=12) as response:
                data = json.load(response)
            try:
                with urlopen(f"{FORECAST_URL}?{params}", timeout=12) as response:
                    forecast = json.load(response)
            except (HTTPError, URLError, TimeoutError, OSError):
                forecast = {"list": []}
            self.after(0, lambda: self._show_weather(data, forecast))
        except HTTPError as err:
            message = ("City not found. Try adding the country, e.g. Pune, IN." if err.code == 404
                       else "The weather service rejected the request. Check your API key.")
            self.after(0, lambda: self._show_error(message))
        except (URLError, TimeoutError, OSError):
            self.after(0, lambda: self._show_error("Couldn't reach the weather service. Check your connection."))

    def _show_weather(self, data: dict, forecast: dict) -> None:
        sys = data.get("sys", {})
        self.current_city = f"{data['name']}, {sys.get('country', '')}".rstrip(", ")
        self.timezone_offset = data.get("timezone", 0)
        self.data = data
        self.forecast = forecast
        self.last_city = self.current_city
        self.status_text = "Live weather updated"
        self.status_kind = "ok"
        self._save_settings()
        self.render()

    def _show_error(self, message: str) -> None:
        self.data = None
        self.forecast = {"list": []}
        self.status_text = message
        self.status_kind = "error"
        self.render()

    def toggle_unit(self) -> None:
        self.unit = "imperial" if self.unit == "metric" else "metric"
        self._save_settings()
        if self.current_city:
            self.search_city(self.current_city)
        else:
            self.render()

    def save_current(self) -> None:
        if not self.current_city:
            self.status_text = "Search for a city before saving it."
            self.status_kind = "error"
            self.render()
            return
        if self.current_city not in self.favorites:
            self.favorites.append(self.current_city)
            self.favorites = self.favorites[-8:]
            self._save_settings()
            self.status_text = f"Saved {self.current_city}"
            self.status_kind = "ok"
            self.render()

    def remove_favorite(self, city: str) -> None:
        if city in self.favorites:
            self.favorites.remove(city)
            self._save_settings()
            self.render()


if __name__ == "__main__":
    WaterWeather().mainloop()
