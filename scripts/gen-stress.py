#!/usr/bin/env python3
"""Erzeugt den Stresstest: Substitutionen für die Test-SoftIOC und das WEISS-Display.

Nutzung:
    python3 scripts/gen-stress.py [--sectors 10]

Jeder Sektor hat 80 Analog- und 20 Binärkanäle, 10 Sektoren ergeben 1000 PVs.
Geschrieben werden:
    softioc/stress.substitutions        (danach das Image der Test-SoftIOC neu bauen)
    examples/weiss-stress-<N>.opi.json  (in WEISS hochladen, siehe README)
"""
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "WEISS:STRESS:"

COLS, ROWS = 10, 8          # Analogkacheln pro Sektor
BINARY = 20                 # Binärkanäle pro Sektor: 10 Lauflicht, 10 Zählerbits
PER_SECTOR = COLS * ROWS + BINARY
SECTORS_PER_ROW = 5

# Layout in Pixeln
TILE_W, TILE_H, GAP = 30, 18, 4
LED, LED_GAP = 14, 7
PAD, TITLE_H = 10, 20
SECTOR_GAP = 14
HEADER_H = 76
TREND_H = 200
GRID_W = COLS * TILE_W + (COLS - 1) * GAP
GRID_H = ROWS * TILE_H + (ROWS - 1) * GAP
SECTOR_W = 2 * PAD + GRID_W
SECTOR_H = PAD + TITLE_H + 6 + GRID_H + 10 + 2 * LED + LED_GAP + PAD
WIDTH = SECTORS_PER_ROW * SECTOR_W + (SECTORS_PER_ROW - 1) * SECTOR_GAP

# Kachelfarbe nach Wert (Untergrenze, Farbe). Alle Stufen sind mit schwarzer Schrift lesbar.
HEAT = [(None, "#eff6ff"), (20, "#c6dbef"), (40, "#9ecae1"), (60, "#6baed6"), (80, "#4292c6")]
LED_OFF, LED_RUN, LED_BIT = "#dee2e6", "#00ac25", "#0466c8"
TEXT, MUTED, BORDER, TITLE = "#212529", "#495057", "#adb5bd", "#023e7d"
TREND_COLORS = ["#0353a4", "#e8590c", "#2b8a3e", "#ae3ec9", "#c92a2a"]


def pv(sector: int, kind: str, n: int) -> str:
    return f"{PREFIX}S{sector:02d}:{kind}{n:02d}"


def sector_origin(s: int) -> tuple[int, int]:
    """Spalte und Zeile des Sektors s (ab 0) im Sektorraster."""
    return s % SECTORS_PER_ROW, s // SECTORS_PER_ROW


def phase(s: int, row: int, col: int) -> float:
    """Phasenversatz so, dass eine Welle diagonal über alle Sektoren läuft."""
    sc, sr = sector_origin(s)
    gc, gr = sc * COLS + col, sr * ROWS + row
    return (-2 * math.pi * (gc / 25 + gr / 16)) % (2 * math.pi)


def write_substitutions(sectors: int, path: Path):
    total = sectors * PER_SECTOR
    lines = [
        f"# Erzeugt von scripts/gen-stress.py --sectors {sectors}, nicht von Hand ändern.",
        f"# {sectors} Sektoren x ({COLS * ROWS} Analog + {BINARY} Binär) = {total} Kanäle",
        f'global {{ P = "{PREFIX}" }}',
        "",
        'file "stress-control.template" {',
        f'    {{ N = "{total}" }}',
        "}",
        "",
        'file "stress-ai.template" {',
        "pattern { S, N, PHASE }",
    ]
    for s in range(sectors):
        for row in range(ROWS):
            for col in range(COLS):
                n = row * COLS + col + 1
                lines.append(f'    {{ "{s + 1:02d}", "{n:02d}", "{phase(s, row, col):.4f}" }}')
    lines += ["}", "", 'file "stress-bi.template" {', "pattern { S, N, K, CALC, NAME }"]
    for s in range(sectors):
        for k in range(10):
            lines.append(f'    {{ "{s + 1:02d}", "{k + 1:02d}", "{k}", "A%10=B", "Lauflicht {k + 1}" }}')
        for k in range(10):
            lines.append(f'    {{ "{s + 1:02d}", "{k + 11:02d}", "{k}", "(A>>B)&1", "Zaehler Bit {k}" }}')
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Widgets im WEISS-Format (.opi.json) ---------------------------------------------------

def widget(name: str, children: list | None = None, rules: list | None = None, **props) -> dict:
    w = {"widgetName": name, "properties": props}
    if rules:
        w["rules"] = rules
    if children is not None:
        w["children"] = children
    return w


def group(children: list) -> dict:
    x0 = min(c["properties"]["x"] for c in children)
    y0 = min(c["properties"]["y"] for c in children)
    x1 = max(c["properties"]["x"] + c["properties"]["width"] for c in children)
    y1 = max(c["properties"]["y"] + c["properties"]["height"] for c in children)
    return widget("Group", children, x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def label(text, x, y, w, h, size=12, color=TEXT, bold=False, align="left", **extra) -> dict:
    return widget("TextLabel", label=text, x=x, y=y, width=w, height=h, fontSize=size,
                  textColor=color, fontBold=bold, textHAlign=align, **extra)


def panel(x, y, w, h, alias) -> dict:
    return widget("Rectangle", alias=alias, x=x, y=y, width=w, height=h, backgroundColor="#ffffff",
                  borderColor=BORDER, borderStyle="solid", borderWidth=1, borderRadius=4)


def swatch(x, y, color="transparent", border=BORDER, border_width=1) -> dict:
    return widget("Rectangle", x=x, y=y, width=14, height=14, backgroundColor=color,
                  borderColor=border, borderStyle="solid", borderWidth=border_width, borderRadius=2)


def value(pv_name, x, y, w, h, units="", precision=0, **extra) -> dict:
    return widget("TextUpdate", pvName=pv_name, x=x, y=y, width=w, height=h, fontSize=13,
                  textHAlign="right", backgroundColor="#f1f3f5", borderRadius=3,
                  precisionFromPV=False, precision=precision, unitsFromPV=False, units=units, **extra)


def heat_rule(pv_name: str) -> dict:
    rulesets = []
    for limit, color in HEAT:
        op, val = ("<", str(HEAT[1][0])) if limit is None else (">=", str(limit))
        rulesets.append({"conditions": [{"pvName": pv_name, "operator": op, "value": val}],
                         "value": color})
    return {"name": "Farbe nach Wert", "targetProperty": "backgroundColor", "rulesets": rulesets}


def header(x0, y0, sectors: int) -> dict:
    total = sectors * PER_SECTOR
    w = [panel(x0, y0, WIDTH, HEADER_H, "Kopfzeile"),
         label(f"WEISS Stresstest · {total} PVs", x0 + 16, y0 + 8, 440, 32, 22, TITLE, True),
         label(f"{sectors} Sektoren × ({COLS * ROWS} Analog + {BINARY} Binär), "
               f"Präfix {PREFIX}", x0 + 16, y0 + 44, 480, 20, 12, MUTED)]

    def caption(text, x, width):
        w.append(label(text, x, y0 + 8, width, 16, 11, MUTED))

    x = x0 + 520
    caption("Update-Rate", x, 110)
    w.append(widget("SelectionBox", pvName=PREFIX + "RATE", x=x, y=y0 + 28, width=110, height=32,
                    label="", fontSize=13, backgroundColor="#ffffff"))
    x += 125
    caption("Erzeugte Last", x, 120)
    w.append(value(PREFIX + "LOAD", x, y0 + 28, 120, 32, units="Upd/s"))
    x += 135
    caption("Takt", x, 100)
    w.append(value(PREFIX + "TICKS", x, y0 + 28, 100, 32))
    for name, text in (("AMPL", "Amplitude"), ("NOISE", "Rauschen")):
        x += 115
        caption(text, x, 170)
        w.append(widget("Slider", pvName=PREFIX + name, x=x, y=y0 + 28, width=170, height=32,
                        horizontal=True))
        w.append(value(PREFIX + name, x + 175, y0 + 28, 56, 32, precision=1))
        x += 135

    # Legende: Kachelfarbe, Alarmrahmen, LEDs
    x = x0 + WIDTH - 420
    caption("Kachel = Wert (Farbe) und Alarm (Rahmen)", x, 400)
    bounds = ["< 20", "20–40", "40–60", "60–80", "≥ 80"]
    for i, (_, color) in enumerate(HEAT):
        w.append(swatch(x + i * 62, y0 + 30, color))
        w.append(label(bounds[i], x + i * 62 + 18, y0 + 27, 44, 20, 11))
    legend = [(swatch(x, y0 + 54, border="#ffff00", border_width=3), "MINOR > 85 / < 15", 110),
              (swatch(x + 135, y0 + 54, border="#ff0000", border_width=3), "MAJOR > 95 / < 5", 105),
              (swatch(x + 265, y0 + 54, LED_RUN), "Lauflicht", 55),
              (swatch(x + 345, y0 + 54, LED_BIT), "Zähler", 50)]
    for sw, text, width in legend:
        w.append(sw)
        w.append(label(text, sw["properties"]["x"] + 18, y0 + 51, width, 20, 11))
    return group(w)


def sector(s: int, x, y) -> dict:
    num = s + 1
    w = [panel(x, y, SECTOR_W, SECTOR_H, f"Sektor {num:02d}"),
         label(f"Sektor {num:02d}", x + PAD, y + PAD, 120, TITLE_H, 13, TEXT, True),
         label(f"S{num:02d}:A01–A{COLS * ROWS}, B01–B{BINARY}", x + SECTOR_W - PAD - 200, y + PAD,
               200, TITLE_H, 10, MUTED, align="right")]
    gy = y + PAD + TITLE_H + 6
    for row in range(ROWS):
        for col in range(COLS):
            n = row * COLS + col + 1
            name = pv(num, "A", n)
            w.append(widget("TextUpdate", rules=[heat_rule(name)], alias=f"A{n:02d}",
                            pvName=name, x=x + PAD + col * (TILE_W + GAP),
                            y=gy + row * (TILE_H + GAP), width=TILE_W, height=TILE_H,
                            fontSize=10, textHAlign="center", backgroundColor="#ced4da",
                            precisionFromPV=False, precision=0, unitsFromPV=False, units=""))
    ly = gy + GRID_H + 10
    for k in range(BINARY):
        row, col = divmod(k, COLS)
        on = LED_RUN if row == 0 else LED_BIT
        w.append(widget("BitIndicator", alias=f"B{k + 1:02d}", pvName=pv(num, "B", k + 1),
                        x=x + PAD + col * (TILE_W + GAP) + (TILE_W - LED) // 2,
                        y=ly + row * (LED + LED_GAP), width=LED, height=LED,
                        onColor=on, offColor=LED_OFF, borderStyle="solid", borderWidth=1,
                        borderColor="#868e96"))
    return group(w)


def trend(x, y, sectors: int) -> dict:
    shown = list(range(1, min(sectors, len(TREND_COLORS)) + 1))
    return widget("GraphY", alias="Trend", x=x, y=y, width=WIDTH, height=TREND_H,
                  pvNames=[pv(s, "A", 1) for s in shown], lineColors=TREND_COLORS[:len(shown)],
                  plotTitle=f"Kanal A01 der Sektoren {shown[0]:02d}–{shown[-1]:02d} "
                            "(Phasenversatz der Welle)",
                  xAxisTitle="Samples", yAxisTitle="Wert", plotBufferSize=200,
                  borderColor=BORDER, borderStyle="solid", borderWidth=1, borderRadius=4)


def build_display(sectors: int) -> list:
    rows = math.ceil(sectors / SECTORS_PER_ROW)
    height = HEADER_H + 14 + rows * SECTOR_H + (rows - 1) * SECTOR_GAP + 14 + TREND_H
    # WEISS zeigt den Ursprung (0, 0) in der Bildschirmmitte, deshalb um ihn zentrieren
    x0, y0 = -(WIDTH // 2), -(height // 2)
    widgets = [widget("GridZone", backgroundColor="#e9ecef", gridLineColor="#dee2e6", gridSize=5,
                      gridLineVisible=True, snapToGrid=True, centerVisible=True,
                      guidesVisible=True, macros={})]
    widgets.append(header(x0, y0, sectors))
    sy = y0 + HEADER_H + 14
    for s in range(sectors):
        sc, sr = sector_origin(s)
        widgets.append(sector(s, x0 + sc * (SECTOR_W + SECTOR_GAP), sy + sr * (SECTOR_H + SECTOR_GAP)))
    widgets.append(trend(x0, sy + rows * SECTOR_H + (rows - 1) * SECTOR_GAP + 14, sectors))
    return widgets


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sectors", type=int, default=10,
                        help=f"Anzahl Sektoren à {PER_SECTOR} PVs (Standard: 10 = 1000 PVs)")
    args = parser.parse_args()
    if not 1 <= args.sectors <= 99:
        parser.error("--sectors muss zwischen 1 und 99 liegen")

    total = args.sectors * PER_SECTOR
    subst = ROOT / "softioc" / "stress.substitutions"
    opi = ROOT / "examples" / f"weiss-stress-{total}.opi.json"
    write_substitutions(args.sectors, subst)
    opi.write_text(json.dumps(build_display(args.sectors), indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"{total} PVs: {subst.relative_to(ROOT)}, {opi.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
