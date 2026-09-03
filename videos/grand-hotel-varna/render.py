#!/usr/bin/env python3
"""
Grand Hotel Varna - "for sale" presentation videos.

Renders six video variations (different formats, pacing and tone) from a
single facts file.  Every frame is drawn with Pillow, encoded with the ffmpeg
binary bundled in `imageio-ffmpeg`, and mixed with a procedurally generated
ambient soundtrack (no external media or licences needed).

Backdrops are procedural "Black Sea resort" scenes.  Drop real photographs
into ./photos (jpg/png) and they are used instead, in filename order.

Usage:
    python3 render.py                 # all five, full quality
    python3 render.py --preview       # quick 640px 12fps check
    python3 render.py --only 1 3      # render selected variations
    python3 render.py --no-audio

Requirements:  pip install pillow numpy imageio-ffmpeg
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "output")
PHOTO_DIR = os.path.join(HERE, "photos")
FACTS = json.load(open(os.path.join(HERE, "hotel_facts.json"), encoding="utf-8"))

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONTS = {
    "serif_b": os.path.join(FONT_DIR, "DejaVuSerif-Bold.ttf"),
    "serif": os.path.join(FONT_DIR, "DejaVuSerif.ttf"),
    "sans_b": os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"),
    "sans": os.path.join(FONT_DIR, "DejaVuSans.ttf"),
}
_font_cache: dict = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONTS[kind], size)
    return _font_cache[key]


# --------------------------------------------------------------------------- #
# Easing / helpers
# --------------------------------------------------------------------------- #
def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out(x: float) -> float:
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def hex2rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def vgradient(w: int, h: int, stops: list) -> np.ndarray:
    """stops: [(pos 0..1, '#rrggbb'), ...] -> float32 HxWx3."""
    ys = np.linspace(0, 1, h, dtype=np.float32)
    out = np.zeros((h, 3), dtype=np.float32)
    pos = [s[0] for s in stops]
    cols = np.array([hex2rgb(s[1]) for s in stops], dtype=np.float32)
    for c in range(3):
        out[:, c] = np.interp(ys, pos, cols[:, c])
    return np.repeat(out[:, None, :], w, axis=1)


def to_img(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def glow_ellipse(img: Image.Image, box, color, blur: int, alpha: int = 255):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse(box, fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


# --------------------------------------------------------------------------- #
# Procedural backdrops (rendered once per scene, oversized for Ken Burns)
# --------------------------------------------------------------------------- #
def bd_sea_horizon(w, h, p, rng):
    sky = vgradient(w, h, [(0, p["sky_top"]), (0.55, p["sky_bot"]), (0.56, p["sea_top"]), (1, p["sea_bot"])])
    img = to_img(sky).convert("RGBA")
    hz = int(h * 0.555)
    sun_r = int(h * 0.09)
    sx, sy = int(w * 0.74), hz - int(sun_r * 0.55)
    glow_ellipse(img, (sx - sun_r * 3, sy - sun_r * 3, sx + sun_r * 3, sy + sun_r * 3), hex2rgb(p["sun"]), 90, 120)
    glow_ellipse(img, (sx - sun_r, sy - sun_r, sx + sun_r, sy + sun_r), hex2rgb(p["sun"]), 6, 255)
    # sun reflection column
    glow_ellipse(img, (sx - sun_r * 0.9, hz, sx + sun_r * 0.9, h), hex2rgb(p["sun"]), 60, 70)
    d = ImageDraw.Draw(img, "RGBA")
    # wave highlights
    for i in range(180):
        y = hz + int((rng.random() ** 1.6) * (h - hz))
        depth = (y - hz) / (h - hz)
        length = int(lerp(6, 110, depth) * (0.5 + rng.random()))
        x = int(rng.random() * w)
        a = int(lerp(40, 120, depth) * rng.random())
        d.line([(x, y), (x + length, y)], fill=hex2rgb(p["wave"]) + (a,), width=max(1, int(depth * 3)))
    # distant headland
    pts = [(0, hz)]
    for i in range(1, 12):
        pts.append((int(w * 0.22 * i / 11), hz - int(h * 0.02 * math.sin(i / 11 * math.pi) * (1 + 0.3 * rng.random()))))
    pts.append((int(w * 0.22), hz))
    d.polygon(pts, fill=hex2rgb(p["land"]) + (230,))
    return img.convert("RGB")


def bd_hotel_facade(w, h, p, rng):
    sky = vgradient(w, h, [(0, p["sky_top"]), (0.7, p["sky_bot"]), (0.71, p["ground"]), (1, p["ground_bot"])])
    img = to_img(sky).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    gy = int(h * 0.7)
    # main tower (11 storeys) + two lower wings
    tw, th = int(w * 0.26), int(h * 0.58)
    tx = int(w * 0.5 - tw / 2)
    ty = gy - th
    wall = hex2rgb(p["wall"])
    d.rectangle((tx - int(w * 0.16), gy - int(th * 0.32), tx, gy), fill=wall)
    d.rectangle((tx + tw, gy - int(th * 0.32), tx + tw + int(w * 0.16), gy), fill=wall)
    d.rectangle((tx, ty, tx + tw, gy), fill=tuple(int(c * 1.08) for c in wall))
    d.rectangle((tx, ty - int(h * 0.02), tx + tw, ty), fill=hex2rgb(p["roof"]))
    # windows grid
    storeys, cols = 11, 9
    fh = th / (storeys + 0.6)
    cw = tw / (cols + 1)
    win = hex2rgb(p["window"])
    for s in range(storeys):
        for c in range(cols):
            if rng.random() < 0.15:
                continue
            x0 = tx + cw * (c + 0.65)
            y0 = ty + fh * (s + 0.75)
            a = int(150 + 105 * rng.random())
            d.rectangle((x0, y0, x0 + cw * 0.55, y0 + fh * 0.5), fill=win + (a,))
    for wing_x in (tx - int(w * 0.16), tx + tw):
        for s in range(3):
            for c in range(6):
                if rng.random() < 0.2:
                    continue
                x0 = wing_x + (w * 0.16 / 7) * (c + 0.6)
                y0 = gy - th * 0.32 + (th * 0.32 / 3.6) * (s + 0.6)
                d.rectangle((x0, y0, x0 + w * 0.012, y0 + th * 0.045), fill=win + (200,))
    # pool with reflection
    px0, px1 = int(w * 0.36), int(w * 0.64)
    d.rounded_rectangle((px0, gy + int(h * 0.08), px1, gy + int(h * 0.2)), radius=40, fill=hex2rgb(p["pool"]))
    for i in range(60):
        x = rng.uniform(px0, px1)
        y = rng.uniform(gy + h * 0.09, gy + h * 0.19)
        d.line([(x, y), (x + rng.uniform(10, 60), y)], fill=win + (int(60 + 90 * rng.random()),), width=2)
    # trees in the park
    for i in range(26):
        x = rng.uniform(0, w)
        if px0 - 80 < x < px1 + 80:
            continue
        r = rng.uniform(h * 0.03, h * 0.07)
        y = gy + rng.uniform(h * 0.02, h * 0.12)
        d.rectangle((x - 4, y, x + 4, y + r * 0.8), fill=hex2rgb(p["trunk"]))
        d.ellipse((x - r, y - r * 1.4, x + r, y + r * 0.2), fill=hex2rgb(p["tree"]))
    # atmosphere glow at horizon
    glow_ellipse(img, (-w * 0.2, gy - h * 0.15, w * 1.2, gy + h * 0.1), hex2rgb(p["sky_bot"]), 80, 90)
    return img.convert("RGB")


def bd_marina(w, h, p, rng):
    sky = vgradient(w, h, [(0, p["sky_top"]), (0.5, p["sky_bot"]), (0.51, p["sea_top"]), (1, p["sea_bot"])])
    img = to_img(sky).convert("RGBA")
    hz = int(h * 0.5)
    glow_ellipse(img, (w * 0.1, hz - h * 0.25, w * 0.9, hz + h * 0.05), hex2rgb(p["sun"]), 120, 110)
    d = ImageDraw.Draw(img, "RGBA")
    # pier
    d.rectangle((0, hz + h * 0.22, w * 0.75, hz + h * 0.27), fill=hex2rgb(p["pier"]))
    for x in range(0, int(w * 0.75), 90):
        d.rectangle((x, hz + h * 0.27, x + 14, hz + h * 0.42), fill=hex2rgb(p["pier"]))
    # yachts
    x = w * 0.05
    while x < w * 0.95:
        hull_w = rng.uniform(w * 0.05, w * 0.11)
        mast_h = rng.uniform(h * 0.22, h * 0.42)
        base_y = hz + h * 0.2
        hull = hex2rgb(p["hull"])
        d.polygon([(x, base_y), (x + hull_w, base_y), (x + hull_w * 0.9, base_y + h * 0.03), (x + hull_w * 0.1, base_y + h * 0.03)], fill=hull)
        mx = x + hull_w * 0.5
        d.line([(mx, base_y), (mx, base_y - mast_h)], fill=hull, width=4)
        d.polygon([(mx, base_y - mast_h), (mx + hull_w * 0.4, base_y - mast_h * 0.15), (mx, base_y - mast_h * 0.15)], fill=hex2rgb(p["sail"]) + (200,))
        d.ellipse((mx - 4, base_y - mast_h - 4, mx + 4, base_y - mast_h + 4), fill=hex2rgb(p["light"]))
        # reflection
        d.line([(mx, base_y + h * 0.03), (mx, base_y + h * 0.03 + mast_h * 0.6)], fill=hull + (70,), width=3)
        x += hull_w * rng.uniform(1.4, 2.2)
    for i in range(160):
        y = hz + int((rng.random() ** 1.4) * (h - hz))
        depth = (y - hz) / (h - hz)
        xx = int(rng.random() * w)
        d.line([(xx, y), (xx + int(lerp(8, 120, depth)), y)], fill=hex2rgb(p["wave"]) + (int(30 + 100 * rng.random() * depth),), width=2)
    return img.convert("RGB")


def bd_spa(w, h, p, rng):
    base = vgradient(w, h, [(0, p["top"]), (1, p["bot"])])
    img = to_img(base).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = w * 0.68, h * 0.55
    for i in range(14):
        r = h * 0.06 * (i + 1)
        d.ellipse((cx - r, cy - r * 0.55, cx + r, cy + r * 0.55), outline=hex2rgb(p["ring"]) + (int(120 - i * 7),), width=3)
    for i in range(45):
        r = rng.uniform(10, 70)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        glow_ellipse(img, (x - r, y - r, x + r, y + r), hex2rgb(p["bokeh"]), 14, int(40 + 90 * rng.random()))
    # steam bands
    for i in range(6):
        y = rng.uniform(h * 0.1, h * 0.9)
        glow_ellipse(img, (-w * 0.1, y - h * 0.04, w * 1.1, y + h * 0.04), hex2rgb(p["steam"]), 60, 45)
    return img.convert("RGB")


def bd_map(w, h, p, rng):
    base = vgradient(w, h, [(0, p["top"]), (1, p["bot"])])
    img = to_img(base).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    # grid
    for x in range(0, w, 80):
        d.line([(x, 0), (x, h)], fill=hex2rgb(p["grid"]) + (35,), width=1)
    for y in range(0, h, 80):
        d.line([(0, y), (w, y)], fill=hex2rgb(p["grid"]) + (35,), width=1)
    # schematic coastline (land on the left, sea on the right)
    pts = []
    for i in range(0, h + 40, 40):
        pts.append((w * 0.52 + w * 0.09 * math.sin(i / h * 3.0) + w * 0.03 * math.sin(i / h * 9.1), i))
    land = [(0, 0)] + pts + [(0, h)]
    d.polygon(land, fill=hex2rgb(p["land"]) + (255,))
    d.line(pts, fill=hex2rgb(p["coast"]) + (200,), width=5)
    return img.convert("RGB")


def bd_abstract(w, h, p, rng):
    base = vgradient(w, h, [(0, p["top"]), (1, p["bot"])])
    img = to_img(base).convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(18):
        x = rng.uniform(-w * 0.2, w * 1.2)
        d.line([(x, h), (x + w * 0.35, 0)], fill=hex2rgb(p["line"]) + (int(20 + 50 * rng.random()),), width=int(rng.uniform(1, 5)))
    for i in range(70):
        r = rng.uniform(2, 7)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        d.ellipse((x - r, y - r, x + r, y + r), fill=hex2rgb(p["dot"]) + (int(60 + 160 * rng.random()),))
    glow_ellipse(img, (w * 0.55, -h * 0.3, w * 1.3, h * 0.6), hex2rgb(p["glow"]), 160, 70)
    return img.convert("RGB")


BACKDROPS: dict[str, Callable] = {
    "sea": bd_sea_horizon,
    "hotel": bd_hotel_facade,
    "marina": bd_marina,
    "spa": bd_spa,
    "map": bd_map,
    "abstract": bd_abstract,
}


# --------------------------------------------------------------------------- #
# Scene / layer model
# --------------------------------------------------------------------------- #
@dataclass
class Layer:
    kind: str  # title | sub | body | stat | chip | rule | bars | route | footer | box
    text: str = ""
    x: float = 0.08  # relative to frame (0..1); negative -> anchor from right
    y: float = 0.5
    size: float = 0.08  # relative to frame height
    color: str = "#ffffff"
    fontkind: str = "sans"
    start: float = 0.3  # seconds after scene start
    dur: float = 0.8  # fade / slide duration
    align: str = "left"  # left | center | right
    anim: str = "rise"  # rise | fade | count | wipe
    extra: dict = field(default_factory=dict)


@dataclass
class Scene:
    duration: float
    backdrop: str
    palette: dict
    layers: list
    zoom: tuple = (1.0, 1.12)
    pan: tuple = ((0.5, 0.5), (0.5, 0.5))
    tint: tuple = (0, 0, 0, 90)  # RGBA darkening overlay for legibility
    vignette: float = 0.55


@dataclass
class Variation:
    idx: int
    slug: str
    title: str
    size: tuple
    fps: int
    scenes: list
    xfade: float = 0.7
    music: str = "calm"  # calm | bright | pulse
    accent: str = "#d4af37"
    watermark: str = ""


# --------------------------------------------------------------------------- #
# Text drawing
# --------------------------------------------------------------------------- #
def wrap_text(text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list:
    lines = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if fnt.getlength(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
    return lines


def draw_text_block(d: ImageDraw.ImageDraw, W, H, layer: Layer, text: str, alpha: float, dy: int, accent: str):
    fsize = max(10, int(layer.size * H))
    fnt = font(layer.fontkind, fsize)
    max_w = int(W * layer.extra.get("max_w", 0.84))
    lines = wrap_text(text, fnt, max_w)
    lh = int(fsize * layer.extra.get("line_h", 1.15))
    total_h = lh * len(lines)
    y = int(layer.y * H) + dy
    if layer.extra.get("anchor_center_y"):
        y -= total_h // 2
    col = hex2rgb(layer.color) + (int(255 * alpha),)
    shadow = (0, 0, 0, int(140 * alpha))
    for i, ln in enumerate(lines):
        tw = fnt.getlength(ln)
        if layer.align == "center":
            x = int(W * layer.x - tw / 2)
        elif layer.align == "right":
            x = int(W * layer.x - tw)
        else:
            x = int(W * layer.x)
        yy = y + i * lh
        d.text((x + 3, yy + 3), ln, font=fnt, fill=shadow)
        d.text((x, yy), ln, font=fnt, fill=col)
    if layer.extra.get("underline"):
        ux0 = int(W * layer.x) if layer.align == "left" else int(W * layer.x - (fnt.getlength(lines[0]) / 2 if layer.align == "center" else fnt.getlength(lines[0])))
        uw = int(min(max_w, fnt.getlength(lines[0])))
        uy = y + total_h + int(fsize * 0.25)
        d.rectangle((ux0, uy, ux0 + int(uw * alpha), uy + max(2, fsize // 12)), fill=hex2rgb(accent) + (int(255 * alpha),))
    return total_h


def draw_layer(overlay: Image.Image, W: int, H: int, layer: Layer, t: float, accent: str, scene_t_end: float):
    """t = seconds since scene start."""
    prog = (t - layer.start) / max(layer.dur, 0.01)
    if prog <= 0:
        return
    a = ease_out(prog)
    # fade out shortly before scene end for layers flagged to do so
    if layer.extra.get("out"):
        a *= clamp01((scene_t_end - t) / 0.5)
    d = ImageDraw.Draw(overlay, "RGBA")
    dy = int((1 - a) * H * 0.04) if layer.anim == "rise" else 0

    if layer.kind in ("title", "sub", "body"):
        draw_text_block(d, W, H, layer, layer.text, a, dy, accent)

    elif layer.kind == "stat":
        # big number counting up + caption below
        target = layer.extra["value"]
        cnt = ease_out(prog) if layer.anim == "count" else 1.0
        val = int(round(target * cnt))
        fmt = layer.extra.get("fmt", "{:,}")
        txt = layer.extra.get("prefix", "") + fmt.format(val) + layer.extra.get("suffix", "")
        num_layer = Layer("title", txt, layer.x, layer.y, layer.size, layer.color, "serif_b", align=layer.align)
        h1 = draw_text_block(d, W, H, num_layer, txt, a, dy, accent)
        cap = Layer("body", layer.text, layer.x, layer.y + (h1 + H * 0.012) / H, layer.size * 0.3, layer.extra.get("cap_color", "#e9e4d6"), "sans", align=layer.align, extra={"max_w": layer.extra.get("max_w", 0.3)})
        draw_text_block(d, W, H, cap, layer.text, a, dy, accent)

    elif layer.kind == "chip":
        fsize = int(layer.size * H)
        fnt = font("sans_b", fsize)
        tw = fnt.getlength(layer.text)
        padx, pady = int(fsize * 0.9), int(fsize * 0.5)
        if layer.align == "center":
            x0 = int(W * layer.x - tw / 2 - padx)
        elif layer.align == "right":
            x0 = int(W * layer.x - tw - 2 * padx)
        else:
            x0 = int(W * layer.x)
        y0 = int(layer.y * H) + dy
        fill = hex2rgb(layer.extra.get("bg", accent)) + (int(235 * a),)
        d.rounded_rectangle((x0, y0, x0 + tw + 2 * padx, y0 + fsize + 2 * pady), radius=int(fsize * 0.9), fill=fill)
        d.text((x0 + padx, y0 + pady - fsize * 0.08), layer.text, font=fnt, fill=hex2rgb(layer.color) + (int(255 * a),))

    elif layer.kind == "rule":
        x0, y0 = int(W * layer.x), int(H * layer.y)
        length = int(W * layer.extra.get("len", 0.12) * a)
        d.rectangle((x0, y0, x0 + length, y0 + max(2, int(H * 0.004))), fill=hex2rgb(layer.color) + (255,))

    elif layer.kind == "box":
        # translucent panel for legibility
        x0, y0 = int(W * layer.x), int(H * layer.y)
        x1, y1 = int(W * layer.extra["x1"]), int(H * layer.extra["y1"])
        d.rounded_rectangle((x0, y0, x1, y1), radius=int(H * 0.02), fill=hex2rgb(layer.color) + (int(layer.extra.get("alpha", 150) * a),))

    elif layer.kind == "bars":
        # horizontal bar chart: extra["items"] = [(label, value), ...]
        items = layer.extra["items"]
        maxv = max(v for _, v in items)
        fsize = int(layer.size * H)
        fnt = font("sans", fsize)
        fnt_b = font("sans_b", fsize)
        x0, y0 = int(W * layer.x), int(H * layer.y) + dy
        row_h = int(fsize * 2.4)
        bar_w = int(W * layer.extra.get("bar_w", 0.45))
        label_w = int(W * layer.extra.get("label_w", 0.22))
        for i, (lab, val) in enumerate(items):
            yy = y0 + i * row_h
            la = clamp01((prog * len(items) - i * 0.6))
            la = ease_out(la)
            d.text((x0, yy + fsize * 0.35), lab, font=fnt, fill=hex2rgb(layer.color) + (int(255 * a * la),))
            bx = x0 + label_w
            d.rounded_rectangle((bx, yy + fsize * 0.35, bx + bar_w, yy + fsize * 1.35), radius=6, fill=(255, 255, 255, int(35 * a)))
            bl = int(bar_w * val / maxv * la)
            d.rounded_rectangle((bx, yy + fsize * 0.35, bx + max(bl, 8), yy + fsize * 1.35), radius=6, fill=hex2rgb(accent) + (int(255 * a),))
            d.text((bx + bar_w + fsize * 0.6, yy + fsize * 0.35), f"{val:,}", font=fnt_b, fill=hex2rgb(layer.color) + (int(255 * a * la),))

    elif layer.kind == "route":
        # schematic route with three labelled nodes: extra["nodes"] = [(label, sub), ...]
        nodes = layer.extra["nodes"]
        fsize = int(layer.size * H)
        fnt = font("sans_b", fsize)
        fnt_s = font("sans", int(fsize * 0.8))
        xs = [int(W * xx) for xx in layer.extra["xs"]]
        ys = [int(H * yy) for yy in layer.extra["ys"]]
        # path
        pts = list(zip(xs, ys))
        segs = len(pts) - 1
        drawn = a * segs
        for i in range(segs):
            seg_a = clamp01(drawn - i)
            if seg_a <= 0:
                break
            x_a, y_a = pts[i]
            x_b, y_b = pts[i + 1]
            d.line([(x_a, y_a), (lerp(x_a, x_b, seg_a), lerp(y_a, y_b, seg_a))], fill=hex2rgb(accent) + (255,), width=max(3, int(H * 0.006)))
        for i, ((lab, sub), (x, y)) in enumerate(zip(nodes, pts)):
            na = ease_out(clamp01(drawn - i + 1))
            r = int(H * 0.014)
            d.ellipse((x - r * 2.2, y - r * 2.2, x + r * 2.2, y + r * 2.2), fill=hex2rgb(accent) + (int(70 * na),))
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(255 * na)))
            d.text((x + r * 2.6, y - fsize * 0.9), lab, font=fnt, fill=(255, 255, 255, int(255 * na)))
            d.text((x + r * 2.6, y + fsize * 0.15), sub, font=fnt_s, fill=hex2rgb(layer.color) + (int(255 * na),))

    elif layer.kind == "list":
        items = layer.extra["items"]
        fsize = int(layer.size * H)
        fnt = font(layer.fontkind, fsize)
        x0, y0 = int(W * layer.x), int(H * layer.y)
        row_h = int(fsize * layer.extra.get("row_h", 1.9))
        for i, it in enumerate(items):
            ia = ease_out(clamp01(prog * (len(items) * 0.7) - i * 0.7))
            ddy = int((1 - ia) * H * 0.02)
            yy = y0 + i * row_h + ddy
            r = int(fsize * 0.22)
            d.ellipse((x0, yy + fsize * 0.45, x0 + 2 * r, yy + fsize * 0.45 + 2 * r), fill=hex2rgb(accent) + (int(255 * ia * a),))
            d.text((x0 + r * 4 + 3, yy + 3), it, font=fnt, fill=(0, 0, 0, int(120 * ia * a)))
            d.text((x0 + r * 4, yy), it, font=fnt, fill=hex2rgb(layer.color) + (int(255 * ia * a),))


# --------------------------------------------------------------------------- #
# Frame composition
# --------------------------------------------------------------------------- #
def vignette_mask(W: int, H: int, strength: float) -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx / W - 0.5) * 2
    ny = (yy / H - 0.5) * 2
    r = np.sqrt(nx * nx + ny * ny) / math.sqrt(2)
    return (1 - strength * np.clip(r - 0.35, 0, 1) ** 1.6 / (0.65**1.6)).astype(np.float32)[..., None]


class SceneRenderer:
    OVERSCAN = 1.35

    def __init__(self, scene: Scene, W: int, H: int, photo: Optional[str], seed: int):
        self.scene, self.W, self.H = scene, W, H
        bw, bh = int(W * self.OVERSCAN), int(H * self.OVERSCAN)
        if photo:
            im = Image.open(photo).convert("RGB")
            # cover-fit
            s = max(bw / im.width, bh / im.height)
            im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
            left, top = (im.width - bw) // 2, (im.height - bh) // 2
            self.base = im.crop((left, top, left + bw, top + bh))
        else:
            rng = np.random.default_rng(seed)
            self.base = BACKDROPS[scene.backdrop](bw, bh, scene.palette, rng)
        self.tint = Image.new("RGBA", (W, H), scene.tint)
        self.vig = vignette_mask(W, H, scene.vignette)

    def backdrop(self, t: float) -> Image.Image:
        u = ease_in_out(t / self.scene.duration)
        z = lerp(self.scene.zoom[0], self.scene.zoom[1], u)
        cx = lerp(self.scene.pan[0][0], self.scene.pan[1][0], u) * self.base.width
        cy = lerp(self.scene.pan[0][1], self.scene.pan[1][1], u) * self.base.height
        cw, ch = self.W * self.OVERSCAN / z, self.H * self.OVERSCAN / z
        x0 = min(max(cx - cw / 2, 0), self.base.width - cw)
        y0 = min(max(cy - ch / 2, 0), self.base.height - ch)
        crop = self.base.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))
        img = crop.resize((self.W, self.H), Image.BILINEAR).convert("RGBA")
        img.alpha_composite(self.tint)
        arr = np.asarray(img.convert("RGB"), dtype=np.float32) * self.vig
        return Image.fromarray(arr.astype(np.uint8), "RGB").convert("RGBA")

    def frame(self, t: float, accent: str, watermark: str) -> Image.Image:
        img = self.backdrop(t)
        overlay = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        for layer in self.scene.layers:
            draw_layer(overlay, self.W, self.H, layer, t, accent, self.scene.duration)
        img.alpha_composite(overlay)
        if watermark:
            d = ImageDraw.Draw(img, "RGBA")
            fnt = font("sans", int(self.H * 0.018))
            d.text((self.W - fnt.getlength(watermark) - int(self.W * 0.03), self.H - int(self.H * 0.045)), watermark, font=fnt, fill=(255, 255, 255, 120))
        return img


# --------------------------------------------------------------------------- #
# Audio (procedural, no external files)
# --------------------------------------------------------------------------- #
def make_audio(path: str, seconds: float, style: str, seed: int = 7, sr: int = 44100):
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float32) / sr

    # sea: low-passed noise (FFT filter), slowly modulated
    noise = rng.standard_normal(n).astype(np.float32)
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    spec *= 1.0 / (1.0 + (freqs / 350.0) ** 2)
    sea = np.fft.irfft(spec, n).astype(np.float32)
    sea /= (np.abs(sea).max() + 1e-6)
    swell = 0.55 + 0.45 * np.sin(2 * math.pi * 0.09 * t + 1.0) * np.sin(2 * math.pi * 0.031 * t)
    sea *= swell.astype(np.float32)

    # pad chords
    if style == "bright":
        prog = [(261.63, 329.63, 392.0), (293.66, 349.23, 440.0), (329.63, 392.0, 493.88), (261.63, 329.63, 392.0)]
        bar = 4.0
    elif style == "pulse":
        prog = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
        bar = 2.4
    else:
        prog = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
        bar = 5.0
    pad = np.zeros(n, dtype=np.float32)
    nbars = int(math.ceil(seconds / bar))
    for bi in range(nbars):
        chord = prog[bi % len(prog)]
        s0, s1 = int(bi * bar * sr), min(int((bi + 1.15) * bar * sr), n)
        if s0 >= n:
            break
        tt = t[s0:s1] - t[s0]
        env = np.minimum(tt / 1.2, 1.0) * np.clip((bar * 1.15 - tt) / 1.5, 0, 1)
        seg = np.zeros_like(tt)
        for f in chord:
            for octv, amp in ((0.5, 0.5), (1.0, 0.35), (2.0, 0.12)):
                seg += amp * np.sin(2 * math.pi * f * octv * tt + rng.uniform(0, 6.28)) * (1 + 0.02 * np.sin(2 * math.pi * 0.3 * tt))
        pad[s0:s1] += seg * env * 0.08
    mix = sea * 0.09 + pad
    if style == "pulse":
        bpm = 100
        beat = 60 / bpm
        kick = np.zeros(n, dtype=np.float32)
        for k_i in range(int(seconds / beat)):
            s0 = int(k_i * beat * sr)
            L = min(int(0.18 * sr), n - s0)
            tt = t[:L]
            kick[s0 : s0 + L] += np.sin(2 * math.pi * (55 + 90 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 14) * 0.35
        mix += kick
    # master fade
    fade = np.minimum(np.minimum(t / 1.5, 1.0), np.clip((seconds - t) / 2.5, 0, 1))
    mix = np.clip(mix * fade, -0.95, 0.95)
    stereo = np.stack([mix, mix * 0.97 + np.roll(mix, 300) * 0.03], axis=1)
    pcm = (stereo * 32767).astype("<i2")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #
def render_variation(v: Variation, photos: list, audio: bool, preview: bool):
    W, H = v.size
    fps = v.fps
    if preview:
        scale = 640 / max(W, H) if W >= H else 640 / H
        W, H = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
        fps = 12
    total = sum(s.duration for s in v.scenes) - v.xfade * (len(v.scenes) - 1)
    out_path = os.path.join(OUT_DIR, f"{v.idx:02d}_{v.slug}{'_preview' if preview else ''}.mp4")
    wav_path = os.path.join(OUT_DIR, f".{v.slug}.wav")
    if audio:
        make_audio(wav_path, total + 0.2, v.music, seed=v.idx * 11)

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-i", wav_path, "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "21" if not preview else "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    watermark = v.watermark if not photos else ""
    renderers = [SceneRenderer(s, W, H, photos[i % len(photos)] if photos else None, seed=v.idx * 100 + i) for i, s in enumerate(v.scenes)]
    starts = []
    acc = 0.0
    for s in v.scenes:
        starts.append(acc)
        acc += s.duration - v.xfade

    nframes = int(total * fps)
    print(f"[{v.idx}] {v.title}: {W}x{H} @ {fps}fps, {total:.1f}s, {nframes} frames -> {os.path.basename(out_path)}")
    for fi in range(nframes):
        T = fi / fps
        # find current scene (last whose start <= T)
        si = max(i for i, st in enumerate(starts) if st <= T + 1e-6)
        t_in = T - starts[si]
        frame = renderers[si].frame(t_in, v.accent, watermark)
        # crossfade with next scene during overlap
        if si + 1 < len(v.scenes) and T >= starts[si + 1]:
            nxt_t = T - starts[si + 1]
            a = ease_in_out(nxt_t / v.xfade)
            nxt = renderers[si + 1].frame(nxt_t, v.accent, watermark)
            frame = Image.blend(frame, nxt, a)
        # global fade in / out
        g = min(min(T / 0.8, 1.0), max((total - T) / 1.0, 0.0))
        if g < 1:
            frame = Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 255)), frame, g)
        proc.stdin.write(frame.convert("RGB").tobytes())
        if fi % (fps * 5) == 0:
            print(f"    {T:5.1f}s / {total:.1f}s", flush=True)
    proc.stdin.close()
    proc.wait()
    if audio and os.path.exists(wav_path):
        os.remove(wav_path)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {out_path}")
    return out_path


# --------------------------------------------------------------------------- #
# The five variations
# --------------------------------------------------------------------------- #
F = FACTS
NAME = F["name"]
CTA = F["cta"]
CONTACT = F.get("contact") or "Serious enquiries only  |  Price on application"

PAL_DUSK = dict(sky_top="#0b1d3a", sky_bot="#e0743a", sea_top="#7a3a2a", sea_bot="#0a1a2e", sun="#ffcf7a", wave="#ffd9a0", land="#08111f")
PAL_NIGHT_HOTEL = dict(sky_top="#050b18", sky_bot="#2d3f70", ground="#0f1a12", ground_bot="#060a08", wall="#4a4f66", roof="#2b2f42", window="#ffd58a", pool="#1d6f8f", trunk="#1c2418", tree="#1f3a24")
PAL_MARINA = dict(sky_top="#1b1f4a", sky_bot="#f28c5b", sea_top="#6d3a4a", sea_bot="#0c1428", sun="#ffb070", pier="#1a1410", hull="#0f0f14", sail="#f5e9d8", light="#fff2c0", wave="#ffd0a0")
PAL_SPA_WARM = dict(top="#3a1f2b", bot="#0e0a12", ring="#f2c9a2", bokeh="#f7d9b0", steam="#f0e0d0")
PAL_MAP_DARK = dict(top="#0a1628", bot="#04090f", grid="#3d5a80", land="#0f2238", coast="#d4af37")
PAL_GOLD = dict(top="#0d1526", bot="#040810", line="#d4af37", dot="#f1e2b0", glow="#c99a3b")

PAL_DAY = dict(sky_top="#2f7fd6", sky_bot="#bfe3f5", sea_top="#1d8fb5", sea_bot="#0a4a6e", sun="#fff4d6", wave="#ffffff", land="#2f5a3a")
PAL_DAY_HOTEL = dict(sky_top="#3c8fd8", sky_bot="#c7e6f7", ground="#3f7a44", ground_bot="#1f4a2a", wall="#e8e3d8", roof="#b9b1a3", window="#7fb8e0", pool="#2bb1d8", trunk="#3b2b1b", tree="#2f7d3c")
PAL_DAY_MARINA = dict(sky_top="#2d7dd2", sky_bot="#d9eef9", sea_top="#2a9ec4", sea_bot="#0d5a80", sun="#ffffff", pier="#7a5a3a", hull="#f7f7f7", sail="#ffffff", light="#ffffff", wave="#ffffff")
PAL_SPA_COOL = dict(top="#0e5a6a", bot="#04202a", ring="#a6e6e0", bokeh="#c9f4ef", steam="#e0f7f5")
PAL_MAP_LIGHT = dict(top="#eaf2f7", bot="#cfe3ee", grid="#6d8ea8", land="#dfe8d8", coast="#0f6fa8")
PAL_TEAL = dict(top="#083344", bot="#02121a", line="#2dd4bf", dot="#99f6e4", glow="#0ea5a5")

WHITE, GOLD, CREAM, NAVY, TEAL, INK, SAND = "#ffffff", "#d4af37", "#efe6d2", "#0b1d3a", "#2dd4bf", "#0f172a", "#f5efe3"


def var1_cinematic() -> Variation:
    """16:9 cinematic investment teaser - slow, dark, gold accents."""
    gh, cx = F["grand_hotel"], F["complex"]
    return Variation(
        idx=1, slug="cinematic_teaser", title="Cinematic investment teaser (16:9)", size=(1920, 1080), fps=30, music="calm", accent=GOLD,
        watermark="Presentation for sale  |  Indicative visuals",
        scenes=[
            Scene(7.5, "abstract", PAL_GOLD, zoom=(1.0, 1.08), layers=[
                Layer("chip", "EXCLUSIVE OPPORTUNITY  |  FOR SALE", 0.5, 0.36, 0.022, NAVY, start=0.4, align="center"),
                Layer("title", NAME.upper(), 0.5, 0.45, 0.10, WHITE, "serif_b", start=0.9, align="center", extra={"underline": True}),
                Layer("sub", "Resort & Spa  |  Black Sea coast, Bulgaria", 0.5, 0.60, 0.034, CREAM, "serif", start=1.6, align="center"),
            ]),
            Scene(8.0, "sea", PAL_DUSK, zoom=(1.12, 1.0), pan=((0.55, 0.5), (0.45, 0.5)), tint=(0, 0, 0, 70), layers=[
                Layer("chip", "LOCATION", 0.08, 0.20, 0.02, NAVY, start=0.5),
                Layer("title", "St. Constantine & Helena", 0.08, 0.27, 0.075, WHITE, "serif_b", start=0.9, extra={"max_w": 0.7}),
                Layer("body", F["resort_note"] + "  -  a landscaped park setting\n200 m from the beach  |  7 km to Varna  |  20 km to Varna Airport", 0.08, 0.45, 0.03, CREAM, start=1.7, extra={"max_w": 0.7, "line_h": 1.5}),
            ]),
            Scene(8.0, "hotel", PAL_NIGHT_HOTEL, zoom=(1.0, 1.15), pan=((0.5, 0.55), (0.5, 0.45)), tint=(0, 0, 0, 60), layers=[
                Layer("chip", "THE FLAGSHIP", 0.08, 0.16, 0.02, NAVY, start=0.5),
                Layer("stat", "double rooms", 0.08, 0.24, 0.13, WHITE, start=0.9, anim="count", extra={"value": gh["double_rooms"]}),
                Layer("stat", "suites", 0.36, 0.24, 0.13, WHITE, start=1.3, anim="count", extra={"value": gh["suites"]}),
                Layer("stat", "storeys, 5-star", 0.56, 0.24, 0.13, WHITE, start=1.7, anim="count", extra={"value": gh["storeys"]}),
                Layer("body", "Conference halls for 20 to 220 delegates  |  6 restaurants  |  sky bar, lobby bar, Viennese cafe", 0.08, 0.72, 0.028, CREAM, start=2.6, extra={"max_w": 0.84}),
            ]),
            Scene(8.0, "marina", PAL_MARINA, zoom=(1.0, 1.1), pan=((0.4, 0.5), (0.6, 0.5)), tint=(0, 0, 0, 60), layers=[
                Layer("chip", "THE COMPLEX", 0.08, 0.16, 0.02, NAVY, start=0.5),
                Layer("stat", "rooms across 5 hotels", 0.08, 0.24, 0.13, WHITE, start=0.9, anim="count", extra={"value": cx["rooms"], "max_w": 0.35}),
                Layer("stat", "apartments", 0.46, 0.24, 0.13, WHITE, start=1.3, anim="count", extra={"value": cx["apartments"]}),
                Layer("body", "Grand Hotel Varna 5*  |  Dolphin  |  Dolphin Marina  |  Rubin  |  Lebed\nYacht marina  |  Beach restaurant  |  Park & gardens", 0.08, 0.66, 0.028, CREAM, start=2.4, extra={"max_w": 0.84, "line_h": 1.5}),
            ]),
            Scene(8.0, "spa", PAL_SPA_WARM, zoom=(1.05, 1.0), tint=(0, 0, 0, 40), layers=[
                Layer("chip", "WELLNESS", 0.08, 0.16, 0.02, NAVY, start=0.5),
                Layer("title", "Built on hot mineral springs", 0.08, 0.23, 0.07, WHITE, "serif_b", start=0.9, extra={"max_w": 0.6}),
                Layer("list", "", 0.08, 0.42, 0.03, CREAM, start=1.6, dur=1.6, extra={"items": F["wellness"]}),
            ]),
            Scene(8.0, "abstract", PAL_GOLD, zoom=(1.08, 1.0), layers=[
                Layer("title", CTA, 0.5, 0.40, 0.07, WHITE, "serif_b", start=0.6, align="center", extra={"underline": True, "max_w": 0.8}),
                Layer("sub", CONTACT, 0.5, 0.56, 0.03, CREAM, start=1.4, align="center"),
                Layer("chip", NAME.upper() + "  |  FOR SALE", 0.5, 0.68, 0.02, NAVY, start=2.0, align="center"),
            ]),
        ],
    )


def var2_investor() -> Variation:
    """16:9 investor data deck - clean, numeric, chart-led."""
    gh, cx, mc = F["grand_hotel"], F["complex"], F["market_context"]
    return Variation(
        idx=2, slug="investor_deck", title="Investor data deck (16:9)", size=(1920, 1080), fps=30, music="calm", accent="#0f6fa8",
        
        scenes=[
            Scene(7.0, "map", PAL_MAP_LIGHT, zoom=(1.0, 1.06), tint=(255, 255, 255, 30), vignette=0.2, layers=[
                Layer("chip", "INVESTMENT SUMMARY", 0.08, 0.16, 0.02, WHITE, start=0.4, extra={"bg": "#0f6fa8"}),
                Layer("title", NAME, 0.08, 0.24, 0.09, INK, "serif_b", start=0.8, extra={"underline": True}),
                Layer("body", "5-star resort hotel and multi-hotel complex\nSt. Constantine & Helena, Varna, Bulgaria", 0.08, 0.42, 0.034, "#1e293b", start=1.5, extra={"line_h": 1.45}),
                Layer("route", "", 0.0, 0.0, 0.026, "#334155", start=2.2, dur=2.4, extra={"nodes": [("Varna Airport", "20 km"), ("Varna city", "7 km"), ("Grand Hotel Varna", "200 m to beach")], "xs": [0.6, 0.7, 0.82], "ys": [0.82, 0.62, 0.42]}),
            ]),
            Scene(8.0, "hotel", PAL_DAY_HOTEL, zoom=(1.0, 1.1), tint=(255, 255, 255, 10), vignette=0.3, layers=[
                Layer("box", "", 0.05, 0.12, INK, start=0.2, extra={"x1": 0.95, "y1": 0.88, "alpha": 205}),
                Layer("chip", "ROOM INVENTORY", 0.08, 0.17, 0.02, WHITE, start=0.5, extra={"bg": "#0f6fa8"}),
                Layer("title", "Scale of the complex", 0.08, 0.24, 0.06, WHITE, "serif_b", start=0.8),
                Layer("bars", "", 0.08, 0.38, 0.026, WHITE, start=1.4, dur=2.2, extra={"items": [("Complex rooms", cx["rooms"]), ("Grand Hotel rooms", gh["double_rooms"]), ("Apartments", cx["apartments"]), ("Suites", gh["suites"])], "label_w": 0.2, "bar_w": 0.42}),
                Layer("body", "One 5-star flagship and four 4-star hotels, a yacht marina and beach dining in a single park estate.", 0.08, 0.76, 0.026, CREAM, start=3.2, extra={"max_w": 0.8}),
            ]),
            Scene(8.0, "sea", PAL_DAY, zoom=(1.08, 1.0), tint=(0, 0, 0, 55), layers=[
                Layer("box", "", 0.05, 0.12, INK, start=0.2, extra={"x1": 0.95, "y1": 0.88, "alpha": 190}),
                Layer("chip", "REVENUE STREAMS", 0.08, 0.17, 0.02, WHITE, start=0.5, extra={"bg": "#0f6fa8"}),
                Layer("title", "Diversified operating base", 0.08, 0.24, 0.06, WHITE, "serif_b", start=0.8),
                Layer("list", "", 0.08, 0.36, 0.028, WHITE, start=1.4, dur=2.2, extra={"items": [
                    "Rooms: 1,048 rooms and 98 apartments across five hotels",
                    "F&B: 6 restaurants (main, a-la-carte, fish, Italian, BBQ, Asian, beach) and 4 bars",
                    "MICE: business centre and halls for 20 to 220 delegates",
                    "Wellness: spa on hot mineral springs, indoor mineral pool, balneo programmes",
                    "Leisure: yacht marina, outdoor pool, park and beach 200 m away",
                ], "row_h": 1.85}),
            ]),
            Scene(8.0, "abstract", PAL_MAP_DARK | {"line": "#0f6fa8", "dot": "#bfe3f5", "glow": "#0f6fa8"}, zoom=(1.0, 1.06), tint=(0, 0, 0, 20), layers=[
                Layer("chip", "MARKET CONTEXT  |  PUBLIC RECORD " + str(mc["year"]), 0.08, 0.16, 0.02, WHITE, start=0.4, extra={"bg": "#0f6fa8"}),
                Layer("title", "Institutional interest in the asset", 0.08, 0.23, 0.06, WHITE, "serif_b", start=0.8, extra={"max_w": 0.8}),
                Layer("stat", "agreed price for a 98.27% stake (2023)", 0.08, 0.38, 0.095, WHITE, start=1.3, anim="count", extra={"value": 28, "prefix": "EUR ", "suffix": "m", "max_w": 0.26}),
                Layer("stat", "property assets", 0.40, 0.38, 0.095, WHITE, start=1.7, anim="count", extra={"value": mc["property_assets_eur_m"], "prefix": "EUR ", "suffix": "m", "max_w": 0.24}),
                Layer("stat", "mutual fund portfolio", 0.68, 0.38, 0.095, WHITE, start=2.0, anim="count", extra={"value": mc["fund_portfolio_eur_m"], "prefix": "EUR ", "suffix": "m", "max_w": 0.24}),
                Layer("body", mc["summary"] + ". Source: SeeNews / Property Forum, Nov 2023.", 0.08, 0.72, 0.026, "#bfe3f5", start=2.8, extra={"max_w": 0.84}),
            ]),
            Scene(7.0, "map", PAL_MAP_LIGHT, zoom=(1.06, 1.0), tint=(255, 255, 255, 30), vignette=0.2, layers=[
                Layer("title", CTA, 0.08, 0.30, 0.07, INK, "serif_b", start=0.6, extra={"underline": True, "max_w": 0.8}),
                Layer("body", "Full data room, trading history and asset register available to qualified investors under NDA.", 0.08, 0.58, 0.03, "#1e293b", start=1.3, extra={"max_w": 0.7}),
                Layer("chip", CONTACT, 0.08, 0.74, 0.02, WHITE, start=2.0, extra={"bg": "#0f6fa8"}),
            ]),
        ],
    )


def var3_reel() -> Variation:
    """9:16 vertical social reel - fast, punchy, teal."""
    gh, cx = F["grand_hotel"], F["complex"]
    return Variation(
        idx=3, slug="vertical_reel", title="Vertical social reel (9:16)", size=(1080, 1920), fps=30, xfade=0.4, music="pulse", accent=TEAL,
        scenes=[
            Scene(4.0, "sea", PAL_DAY, zoom=(1.15, 1.0), tint=(0, 0, 0, 80), layers=[
                Layer("chip", "FOR SALE", 0.5, 0.34, 0.018, INK, start=0.2, align="center"),
                Layer("title", "A 5-star resort\non the Black Sea", 0.5, 0.40, 0.055, WHITE, "serif_b", start=0.4, align="center", extra={"max_w": 0.9, "anchor_center_y": False}),
            ]),
            Scene(4.0, "hotel", PAL_DAY_HOTEL, zoom=(1.0, 1.15), tint=(0, 0, 0, 90), layers=[
                Layer("stat", "rooms", 0.5, 0.36, 0.11, WHITE, start=0.2, anim="count", align="center", extra={"value": cx["rooms"], "max_w": 0.8}),
                Layer("body", "across five hotels in one park estate", 0.5, 0.56, 0.026, CREAM, start=0.8, align="center", extra={"max_w": 0.85}),
            ]),
            Scene(4.0, "marina", PAL_DAY_MARINA, zoom=(1.12, 1.0), pan=((0.6, 0.5), (0.4, 0.5)), tint=(0, 0, 0, 80), layers=[
                Layer("title", "Own yacht marina", 0.5, 0.40, 0.055, WHITE, "serif_b", start=0.2, align="center", extra={"max_w": 0.9}),
                Layer("body", "beach restaurant  |  200 m to the sand", 0.5, 0.55, 0.026, CREAM, start=0.7, align="center"),
            ]),
            Scene(4.0, "spa", PAL_SPA_COOL, zoom=(1.0, 1.1), tint=(0, 0, 0, 60), layers=[
                Layer("title", "Spa on hot\nmineral springs", 0.5, 0.36, 0.055, WHITE, "serif_b", start=0.2, align="center", extra={"max_w": 0.9}),
                Layer("body", "indoor mineral pool  |  balneo  |  sauna", 0.5, 0.52, 0.026, CREAM, start=0.7, align="center"),
            ]),
            Scene(4.0, "abstract", PAL_TEAL, zoom=(1.0, 1.08), layers=[
                Layer("title", "6 restaurants\n4 bars\nhalls for 220", 0.5, 0.33, 0.06, WHITE, "serif_b", start=0.2, align="center", extra={"line_h": 1.35}),
            ]),
            Scene(4.0, "map", PAL_MAP_DARK | {"coast": TEAL}, zoom=(1.0, 1.06), tint=(0, 0, 0, 30), layers=[
                Layer("stat", "km from Varna Airport", 0.5, 0.30, 0.11, WHITE, start=0.2, anim="count", align="center", extra={"value": 20, "max_w": 0.8}),
                Layer("body", "7 km to Varna city  |  Bulgaria's oldest seaside resort", 0.5, 0.56, 0.026, CREAM, start=0.8, align="center", extra={"max_w": 0.85}),
            ]),
            Scene(5.0, "abstract", PAL_TEAL, zoom=(1.08, 1.0), layers=[
                Layer("title", NAME, 0.5, 0.36, 0.044, WHITE, "serif_b", start=0.2, align="center", extra={"underline": True, "max_w": 0.95}),
                Layer("sub", CTA, 0.5, 0.49, 0.03, CREAM, start=0.7, align="center", extra={"max_w": 0.9}),
                Layer("chip", "LINK IN BIO", 0.5, 0.60, 0.02, INK, start=1.2, align="center"),
            ]),
        ],
    )


def var4_lifestyle() -> Variation:
    """16:9 lifestyle / guest-experience story - warm, emotive."""
    return Variation(
        idx=4, slug="lifestyle_story", title="Lifestyle & experience story (16:9)", size=(1920, 1080), fps=30, xfade=1.0, music="bright", accent="#f59e0b",
        watermark="Presentation for sale  |  Indicative visuals",
        scenes=[
            Scene(8.0, "sea", PAL_DUSK, zoom=(1.0, 1.12), pan=((0.5, 0.55), (0.5, 0.45)), tint=(0, 0, 0, 50), layers=[
                Layer("sub", "Where the Black Sea meets a landscaped seaside park", 0.5, 0.42, 0.045, CREAM, "serif", start=0.8, align="center", extra={"max_w": 0.8}),
                Layer("title", NAME, 0.5, 0.50, 0.09, WHITE, "serif_b", start=1.5, align="center"),
            ]),
            Scene(8.0, "spa", PAL_SPA_WARM, zoom=(1.1, 1.0), tint=(0, 0, 0, 30), layers=[
                Layer("chip", "MORNING", 0.08, 0.18, 0.02, INK, start=0.5),
                Layer("title", "Hot mineral water, straight from the spring", 0.08, 0.26, 0.065, WHITE, "serif_b", start=0.9, extra={"max_w": 0.65}),
                Layer("body", "Indoor mineral pool, balneo and physiotherapy programmes, sauna and solarium. A wellness product that runs twelve months a year.", 0.08, 0.56, 0.028, CREAM, start=1.9, extra={"max_w": 0.62}),
            ]),
            Scene(8.0, "hotel", PAL_DAY_HOTEL, zoom=(1.0, 1.12), tint=(0, 0, 0, 70), layers=[
                Layer("chip", "AFTERNOON", 0.08, 0.18, 0.02, INK, start=0.5),
                Layer("title", "Two pools, a park and the beach 200 metres away", 0.08, 0.26, 0.065, WHITE, "serif_b", start=0.9, extra={"max_w": 0.7}),
                Layer("body", "Outdoor pool with children's section. Sports and leisure across the resort. Family and conference guests, side by side.", 0.08, 0.56, 0.028, CREAM, start=1.9, extra={"max_w": 0.62}),
            ]),
            Scene(8.0, "marina", PAL_MARINA, zoom=(1.12, 1.0), tint=(0, 0, 0, 50), layers=[
                Layer("chip", "EVENING", 0.08, 0.18, 0.02, INK, start=0.5),
                Layer("title", "Six restaurants, one sunset", 0.08, 0.26, 0.065, WHITE, "serif_b", start=0.9, extra={"max_w": 0.7}),
                Layer("body", "Main, a-la-carte, fish, Italian, barbecue, Asian and beach restaurants. Sky bar, lobby bar, day bar and a Viennese cafe. Yachts at the marina.", 0.08, 0.40, 0.028, CREAM, start=1.9, extra={"max_w": 0.6}),
            ]),
            Scene(8.0, "abstract", PAL_GOLD | {"line": "#f59e0b", "glow": "#f59e0b"}, zoom=(1.0, 1.06), layers=[
                Layer("sub", "A destination with a story, and room to write the next chapter.", 0.5, 0.36, 0.036, CREAM, "serif", start=0.6, align="center", extra={"max_w": 0.8}),
                Layer("title", CTA, 0.5, 0.47, 0.065, WHITE, "serif_b", start=1.3, align="center", extra={"underline": True, "max_w": 0.8}),
                Layer("chip", CONTACT, 0.5, 0.64, 0.02, INK, start=2.0, align="center"),
            ]),
        ],
    )


def var5_square() -> Variation:
    """1:1 LinkedIn / Facebook square - location & connectivity led, professional navy."""
    gh, cx = F["grand_hotel"], F["complex"]
    return Variation(
        idx=5, slug="square_linkedin", title="Square LinkedIn post (1:1)", size=(1080, 1080), fps=30, xfade=0.6, music="calm", accent=GOLD,
        scenes=[
            Scene(6.0, "map", PAL_MAP_DARK, zoom=(1.0, 1.08), tint=(0, 0, 0, 20), layers=[
                Layer("chip", "HOTEL ASSET FOR SALE", 0.08, 0.14, 0.022, NAVY, start=0.3),
                Layer("title", NAME, 0.08, 0.22, 0.068, WHITE, "serif_b", start=0.7, extra={"underline": True, "max_w": 0.85}),
                Layer("sub", "Varna, Bulgaria  |  Black Sea coast", 0.08, 0.36, 0.034, CREAM, "serif", start=1.3),
                Layer("route", "", 0.0, 0.0, 0.028, CREAM, start=1.8, dur=2.4, extra={"nodes": [("Varna Airport", "20 km"), ("Varna city", "7 km"), ("Grand Hotel Varna", "200 m to beach")], "xs": [0.12, 0.35, 0.6], "ys": [0.86, 0.72, 0.56]}),
            ]),
            Scene(6.0, "hotel", PAL_NIGHT_HOTEL, zoom=(1.0, 1.12), tint=(0, 0, 0, 80), layers=[
                Layer("stat", "rooms in the complex", 0.08, 0.16, 0.14, WHITE, start=0.3, anim="count", extra={"value": cx["rooms"], "max_w": 0.5}),
                Layer("stat", "apartments", 0.08, 0.44, 0.14, WHITE, start=0.7, anim="count", extra={"value": cx["apartments"], "max_w": 0.4}),
                Layer("stat", "hotels, 5* + 4*", 0.55, 0.44, 0.14, WHITE, start=1.0, anim="count", extra={"value": 5, "max_w": 0.4}),
                Layer("body", "Flagship: 300 double rooms, 30 suites, 11 storeys. Yacht marina, spa on mineral springs, halls for up to 220 delegates.", 0.08, 0.74, 0.03, CREAM, start=1.8, extra={"max_w": 0.84}),
            ]),
            Scene(6.0, "marina", PAL_MARINA, zoom=(1.1, 1.0), tint=(0, 0, 0, 70), layers=[
                Layer("chip", "WHY NOW", 0.08, 0.14, 0.022, NAVY, start=0.3),
                Layer("list", "", 0.08, 0.24, 0.032, WHITE, start=0.7, dur=2.0, extra={"items": [
                    "Bulgaria's oldest resort, renewed since 2017",
                    "Mixed leisure, MICE and wellness demand",
                    "Institutional transaction on record in 2023",
                    "Single-estate scale: 5 hotels, marina, beach F&B",
                ], "row_h": 2.2}),
            ]),
            Scene(6.0, "abstract", PAL_GOLD, zoom=(1.06, 1.0), layers=[
                Layer("title", CTA, 0.5, 0.40, 0.06, WHITE, "serif_b", start=0.4, align="center", extra={"underline": True, "max_w": 0.85}),
                Layer("sub", CONTACT, 0.5, 0.56, 0.028, CREAM, start=1.1, align="center", extra={"max_w": 0.85}),
                Layer("chip", NAME.upper(), 0.5, 0.68, 0.02, NAVY, start=1.6, align="center"),
            ]),
        ],
    )


def var6_why_now() -> Variation:
    """16:9 ~30 s urgency piece - five numbered reasons to buy now."""
    mc = F["market_context"]
    RED = "#e11d48"
    PAL_EMBER = dict(top="#1a0b10", bot="#050307", line=RED, dot="#fda4af", glow="#9f1239")

    def reason(n: int, head: str, body: str, backdrop: str, pal: dict, zoom, tint=(0, 0, 0, 110)) -> Scene:
        return Scene(4.6, backdrop, pal, zoom=zoom, tint=tint, layers=[
            Layer("chip", f"REASON {n} OF 5", 0.08, 0.16, 0.02, WHITE, start=0.15, dur=0.4, extra={"bg": RED}),
            Layer("title", head, 0.08, 0.24, 0.075, WHITE, "serif_b", start=0.3, dur=0.5, extra={"max_w": 0.84}),
            Layer("body", body, 0.08, 0.56, 0.033, CREAM, start=0.9, dur=0.5, extra={"max_w": 0.8, "line_h": 1.45}),
        ])

    return Variation(
        idx=6, slug="why_buy_now", title="Why buy now - 30 s urgency piece (16:9)", size=(1920, 1080), fps=30, xfade=0.45, music="pulse", accent=RED,
        watermark="Presentation for sale  |  Indicative visuals",
        scenes=[
            Scene(4.0, "abstract", PAL_EMBER, zoom=(1.0, 1.1), layers=[
                Layer("chip", "GRAND HOTEL VARNA  |  FOR SALE", 0.5, 0.34, 0.02, WHITE, start=0.15, dur=0.4, align="center", extra={"bg": RED}),
                Layer("title", "Five reasons to move now", 0.5, 0.42, 0.09, WHITE, "serif_b", start=0.35, dur=0.6, align="center", extra={"underline": True}),
                Layer("sub", "A 5-star Black Sea resort estate does not come to market twice", 0.5, 0.60, 0.03, CREAM, "serif", start=1.0, dur=0.5, align="center", extra={"max_w": 0.85}),
            ]),
            reason(1, "Scale that cannot be rebuilt", "1,048 rooms, 98 apartments, five hotels and a yacht marina on one park estate, 200 m from the beach. Replicating this footprint on Bulgaria's oldest resort is not possible today.", "marina", PAL_MARINA, (1.0, 1.12)),
            reason(2, "Institutional money has already validated it", f"In {mc['year']} Black Sea Property agreed to buy a 98.27% stake for approx. EUR 28 million. The asset is on the radar of professional investors - the next buyer sets the price.", "abstract", PAL_EMBER, (1.1, 1.0), tint=(0, 0, 0, 20)),
            reason(3, "Twelve months of revenue, not one season", "Spa on hot mineral springs, indoor mineral pool, balneo programmes and conference halls for 20 to 220 delegates keep the flagship trading through winter.", "spa", PAL_SPA_WARM, (1.0, 1.1), tint=(0, 0, 0, 70)),
            reason(4, "A resort on the way up", "St. Constantine & Helena has been renewed since 2017 and is one of the most visited resorts in Bulgaria. Varna Airport is 20 km away, the city 7 km.", "sea", PAL_DUSK, (1.12, 1.0), tint=(0, 0, 0, 80)),
            reason(5, "Operating from day one", "A trading 5-star flagship with 300 rooms and 30 suites, six restaurants and four bars. Cash flow from completion, with room to reposition rates and brand.", "hotel", PAL_NIGHT_HOTEL, (1.0, 1.12), tint=(0, 0, 0, 130)),
            Scene(5.5, "abstract", PAL_EMBER, zoom=(1.08, 1.0), layers=[
                Layer("title", "The data room is open now", 0.5, 0.36, 0.08, WHITE, "serif_b", start=0.3, dur=0.5, align="center", extra={"underline": True, "max_w": 0.85}),
                Layer("sub", CTA + "  |  Site visits by appointment", 0.5, 0.52, 0.03, CREAM, start=0.9, dur=0.5, align="center", extra={"max_w": 0.85}),
                Layer("chip", CONTACT, 0.5, 0.64, 0.02, WHITE, start=1.4, dur=0.4, align="center", extra={"bg": RED}),
            ]),
        ],
    )


VARIATIONS = [var1_cinematic, var2_investor, var3_reel, var4_lifestyle, var5_square, var6_why_now]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="fast low-res render")
    ap.add_argument("--only", nargs="*", type=int, help="variation numbers to render (1-6)")
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    photos = sorted(glob.glob(os.path.join(PHOTO_DIR, "*.jp*g")) + glob.glob(os.path.join(PHOTO_DIR, "*.png")))
    if photos:
        print(f"Using {len(photos)} photo(s) from {PHOTO_DIR}")
    outputs = []
    for build in VARIATIONS:
        v = build()
        if args.only and v.idx not in args.only:
            continue
        outputs.append(render_variation(v, photos, audio=not args.no_audio, preview=args.preview))
    print("\nDone:")
    for o in outputs:
        print("  ", o, f"{os.path.getsize(o) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
