#!/usr/bin/env python3
"""Lasttest der PV-Brücke weiss-epicsws: abonniert alle Stresstest-PVs wie der Browser.

Nutzung:
    python3 scripts/check-ws-stress.py [ws://localhost:8080] [--rate 10] [--duration 30] [--sectors 10]

Abonniert die Kanäle WEISS:STRESS:S<ss>:A01..A80 und B01..B20 (siehe scripts/gen-stress.py),
setzt mit --rate die Update-Rate der IOC (pause, 0.1, 0.5, 1, 2, 5, 10 Hz) und gibt jede Sekunde
empfangene Updates, aktive PVs und die Latenz (IOC-Zeitstempel bis Empfang) aus. Am Ende wird die
vorherige Rate wiederhergestellt.
Exit-Code 0 = mindestens 95 % der erwarteten Updates empfangen, 1 = nicht bestanden.
Benötigt: pip install websockets
"""
import argparse
import asyncio
import json
import statistics
import sys
import time

import websockets

PREFIX = "WEISS:STRESS:"
RATE, LOAD = PREFIX + "RATE", PREFIX + "LOAD"
RATES = ["pause", "0.1", "0.5", "1", "2", "5", "10"]  # Index = Wert von WEISS:STRESS:RATE
CONNECT_TIMEOUT_S = 30


def pv_name(raw: str) -> str:
    """Entfernt ein Protokollpräfix wie 'ca://' oder 'pva://', falls die Brücke es mitsendet."""
    return raw.split("://", 1)[-1]


def channels(sectors: int) -> list[str]:
    return [f"{PREFIX}S{s:02d}:{kind}{n:02d}"
            for s in range(1, sectors + 1)
            for kind, count in (("A", 80), ("B", 20))
            for n in range(1, count + 1)]


async def write(ws, pv: str, value):
    await ws.send(json.dumps({"type": "write", "pv": "ca://" + pv, "value": value}))


async def run(args) -> int:
    names = channels(args.sectors)
    wanted = set(names)
    last_update: dict[str, float] = {}
    values: dict[str, object] = {}
    latencies: list[float] = []
    received = 0
    first_all = None
    old_rate = None

    async with websockets.connect(args.url, open_timeout=10, max_queue=None) as ws:
        print(f"Verbunden mit {args.url}, abonniere {len(names)} PVs")
        start = time.monotonic()
        await ws.send(json.dumps({"type": "subscribe", "pvs": ["ca://" + n for n in [RATE, LOAD] + names]}))

        async def receive_until(deadline: float, measure: bool, until_all: bool = False):
            nonlocal received, first_all
            while (remaining := deadline - time.monotonic()) > 0:
                if until_all and first_all is not None and RATE in values:
                    return
                try:
                    raw = await asyncio.wait_for(ws.recv(), remaining)
                except asyncio.TimeoutError:
                    return
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                if msg.get("type") != "update":
                    continue
                name = pv_name(msg.get("pv", ""))
                if "value" in msg:
                    values[name] = msg["value"]
                if name not in wanted or msg.get("connected") is False:
                    continue
                now = time.monotonic()
                last_update[name] = now
                if first_all is None and len(last_update) == len(wanted):
                    first_all = now - start
                if measure:
                    received += 1
                    ts = msg.get("timeStamp") or {}
                    if ts.get("secondsPastEpoch"):
                        stamp = ts["secondsPastEpoch"] + ts.get("nanoseconds", 0) / 1e9
                        latencies.append(time.time() - stamp)

        try:
            await receive_until(time.monotonic() + CONNECT_TIMEOUT_S, measure=False, until_all=True)
            if RATE not in values:
                print(f"FEHLER: kein Wert für {RATE}, läuft die Test-SoftIOC mit Stresstest?",
                      file=sys.stderr)
                return 1
            print(f"Erste Werte aller PVs nach {first_all:.1f} s" if first_all is not None else
                  f"Nach {CONNECT_TIMEOUT_S} s erst {len(last_update)} von {len(wanted)} PVs mit Wert")
            old_rate = values[RATE]
            if args.rate is not None:
                target = RATES.index(args.rate)
                await write(ws, RATE, target)
                deadline = time.monotonic() + CONNECT_TIMEOUT_S
                while values.get(RATE) != target and time.monotonic() < deadline:
                    await receive_until(time.monotonic() + 0.5, measure=False)
                if values.get(RATE) != target:
                    print("FEHLER: neue Rate kam nicht über die Brücke zurück", file=sys.stderr)
                    return 1
                await receive_until(time.monotonic() + 1, measure=False)
            hz = 0.0 if values[RATE] == 0 else float(RATES[int(values[RATE])])
            expected_rate = hz * len(names)
            print(f"IOC-Rate: {RATES[int(values[RATE])]} Hz, erwartet {expected_rate:.0f} Updates/s"
                  f" (IOC meldet {values.get(LOAD)})")
            print(" Sek  Updates/s  aktive PVs  Latenz p50/max [ms]")

            t0 = time.monotonic()
            for sec in range(1, args.duration + 1):
                before, lat_from = received, len(latencies)
                await receive_until(t0 + sec, measure=True)
                window = latencies[lat_from:]
                active = sum(1 for t in last_update.values() if t >= t0 + sec - 1)
                lat = (f"{statistics.median(window) * 1000:7.1f} / {max(window) * 1000:7.1f}"
                       if window else "      - /       -")
                print(f"{sec:4d}  {received - before:9d}  {active:10d}  {lat}")
        except websockets.ConnectionClosed as e:
            print(f"FEHLER: Brücke hat die Verbindung getrennt: {e.rcvd.code if e.rcvd else '?'} "
                  f"{e.rcvd.reason if e.rcvd else ''}", file=sys.stderr)
            return 1
        finally:
            if args.rate is not None and old_rate is not None:
                try:
                    await write(ws, RATE, int(old_rate))
                    print(f"Rate zurückgesetzt auf {RATES[int(old_rate)]} Hz")
                except websockets.ConnectionClosed:
                    print("Rate nicht zurückgesetzt (Verbindung getrennt)", file=sys.stderr)

    rate = received / args.duration
    missing = len(wanted) - len(last_update)
    print(f"Empfangen: {received} Updates in {args.duration} s = {rate:.0f}/s")
    if latencies:
        lat = sorted(latencies)
        print(f"Latenz: p50 {lat[len(lat) // 2] * 1000:.1f} ms, p95 {lat[int(len(lat) * 0.95)] * 1000:.1f} ms, "
              f"max {lat[-1] * 1000:.1f} ms")
    if missing:
        print(f"FEHLER: {missing} PVs ohne Wert", file=sys.stderr)
        return 1
    if expected_rate > 0 and rate < 0.95 * expected_rate:
        print(f"FEHLER: nur {rate / expected_rate:.0%} der erwarteten Updates", file=sys.stderr)
        return 1
    print("OK: alle PVs liefern Werte" + (" in voller Rate" if expected_rate else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", nargs="?", default="ws://localhost:8080")
    parser.add_argument("--rate", choices=RATES, help="Update-Rate der IOC in Hz für den Test")
    parser.add_argument("--duration", type=int, default=20, help="Messdauer in Sekunden (Standard: 20)")
    parser.add_argument("--sectors", type=int, default=10, help="Sektoren wie bei gen-stress.py (Standard: 10)")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
