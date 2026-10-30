#!/bin/sh
# Installiert die Quadlet-Units und die Konfiguration für den aktuellen Benutzer
# (rootless) und lädt systemd neu. Startet die Dienste nicht.
# Nutzung: scripts/install.sh [--with-softioc]
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/containers/systemd"
CONF_DIR="$HOME/.config/weiss"

mkdir -p "$UNIT_DIR" "$CONF_DIR"
cp "$ROOT"/quadlet/*.container "$ROOT"/quadlet/*.network "$ROOT"/quadlet/*.volume "$UNIT_DIR"/

for arg in "$@"; do
    case "$arg" in
        --with-softioc) cp "$ROOT"/quadlet/optional/softioc.container "$UNIT_DIR"/ ;;
        *) echo "Unbekannte Option: $arg" >&2; exit 1 ;;
    esac
done

# Vorhandene Konfiguration nicht überschreiben.
[ -f "$CONF_DIR/weiss.env" ] || cp "$ROOT/quadlet/weiss.env.example" "$CONF_DIR/weiss.env"
[ -f "$CONF_DIR/roles.toml" ] || cp "$ROOT/roles.toml" "$CONF_DIR/roles.toml"

systemctl --user daemon-reload
echo "Units installiert in $UNIT_DIR, Konfiguration in $CONF_DIR."
echo "Nächste Schritte: scripts/build-images.sh && systemctl --user enable --now weiss.service"
