#!/usr/bin/env python3
"""Prüft die PV-Brücke weiss-epicsws über den WebSocket (ohne Anmeldung, nur Port 8080).

Nutzung:
    python3 scripts/check-ws.py [ws://localhost:8080] [--write]

Ohne --write: abonniert WEISS:TEST:COUNTER und wartet auf einen Wert.
Mit --write:  schreibt zusätzlich WEISS:TEST:SETPOINT = 42.5 und wartet,
              bis dieser Wert über die Abo-Updates zurückkommt.
Exit-Code 0 = Prüfung bestanden, 1 = nicht bestanden.
Benötigt: pip install websockets
"""
import asyncio
import json
import sys
import time

import websockets

COUNTER = "WEISS:TEST:COUNTER"
SETPOINT = "WEISS:TEST:SETPOINT"
TIMEOUT_S = 10


def pv_name(raw: str) -> str:
    """Entfernt ein Protokollpräfix wie 'ca://' oder 'pva://', falls die Brücke es mitsendet."""
    return raw.split("://", 1)[-1]


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = args[0] if args else "ws://localhost:8080"
    do_write = "--write" in sys.argv

    seen: dict[str, object] = {}
    deadline = time.monotonic() + TIMEOUT_S

    async with websockets.connect(url, open_timeout=TIMEOUT_S) as ws:
        print(f"Verbunden mit {url}")
        await ws.send(json.dumps({"type": "subscribe", "pvs": ["ca://" + COUNTER, "ca://" + SETPOINT]}))

        if do_write:
            await asyncio.sleep(1)  # kurz warten, bis das Abo steht
            await ws.send(json.dumps({"type": "write", "pv": "ca://" + SETPOINT, "value": 42.5}))
            print("Schreibauftrag gesendet: WEISS:TEST:SETPOINT = 42.5")

        while time.monotonic() < deadline:
            if COUNTER in seen and (not do_write or seen.get(SETPOINT) == 42.5):
                break
            remaining = deadline - time.monotonic()
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), remaining))
            except asyncio.TimeoutError:
                break
            if msg.get("type") != "update":
                continue
            name = pv_name(msg.get("pv", ""))
            seen[name] = msg.get("value")
            print(f"  {name} = {msg.get('value')}")

    if COUNTER not in seen:
        print("FEHLER: kein Lesewert für WEISS:TEST:COUNTER", file=sys.stderr)
        return 1
    if do_write and seen.get(SETPOINT) != 42.5:
        print("FEHLER: Schreibwert 42.5 kam nicht zurück", file=sys.stderr)
        return 1
    print("OK: Lesen" + (" und Schreiben" if do_write else "") + " über die Brücke funktioniert")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
