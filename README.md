# WEISS mit rootless Podman

Betrieb von [WEISS](https://github.com/weiss-controls/weiss) (Web EPICS Interface & Synoptic Studio)
in rootless Podman-Containern, später als systemd-Dienst unter Ubuntu. Die Anleitung zielt auf
**lokale EPICS-Channel-Access-Werte (CA)** und zunächst **HTTP**. Die Schritte für HTTPS stehen
[weiter unten](#später-auf-https-umsteigen).

Dieses Repo enthält nur die Podman-Konfiguration. Der Upstream-Code wird beim Bauen direkt aus Git
geladen. Upstream-Doku: <https://docs.weiss-controls.org/>

> Teststand: Die drei Images bauen, die Test-SoftIOC läuft, und `weiss-epicsws` liest und schreibt
> PVs über den WebSocket (Prüfung mit `scripts/check-ws.py`, siehe unten). Noch nicht geprüft:
> Frontend im Browser, HTTPS und der systemd-Dienst über Quadlet.

## Inhalt

| Datei | Zweck |
|---|---|
| `compose.yaml`, `.env.example` | Schneller Start mit `podman compose` |
| `quadlet/` | systemd-Units (Quadlet) für den Dauerbetrieb |
| `scripts/build-images.sh` | Baut die drei Images aus der Upstream-Git-URL (`--with-softioc`: zusätzlich die Test-IOC) |
| `scripts/install.sh` | Installiert Units und Konfiguration für den aktuellen Benutzer (`--with-softioc`: zusätzlich die Test-IOC) |
| `softioc/` | Optionale Test-SoftIOC mit Testvariablen (`Containerfile`, `test.db`, `st.cmd`) und Stresstest (`stress-*.template`, `stress.substitutions`) |
| `scripts/gen-stress.py`, `scripts/check-ws-stress.py` | Stresstest: erzeugt IOC-Kanäle und Display, misst die PV-Brücke unter Last |
| `examples/` | Beispieldisplays (`weiss-test.bob`, `weiss-stress-1000.opi.json`) |
| `docs/stresstest.md` | Anleitung zum Stresstest mit 1000 PVs, Grafiken in `docs/img/` |
| `quadlet/optional/` | Quadlet-Unit der Test-SoftIOC |
| `roles.toml` | Rollen-Datei (Upstream-Beispiel, siehe [Rollen](#benutzerrollen)) |

## Aufbau

| Container | Aufgabe | Netzwerk |
|---|---|---|
| `weiss` | nginx mit Frontend | Bridge, Host-Port **80** → Container 8081 |
| `weiss-api` | FastAPI-Backend (Login, Git, Snapshots) | Bridge, Host-Port 8000 |
| `weiss-epicsws` | WebSocket-Brücke zu EPICS (CA/PVA) | **Host-Netzwerk**, Port 8080 |
| `weiss-softioc` (optional) | Test-SoftIOC mit `WEISS:TEST:*` | **Host-Netzwerk**, CA 5064, PVA 5075/5076 |

Im HTTP-Modus verbindet sich der **Browser direkt** mit `http://<host>:8000` (API) und
`ws://<host>:8080` (PVs). Beide Ports müssen vom Browser aus erreichbar sein, nicht nur vom Server.
Im HTTPS-Modus läuft beides über nginx (`/api/`, `/ws/`).

## Voraussetzungen (Ubuntu)

```sh
sudo apt install podman podman-compose git     # Ubuntu 24.04: Podman 4.9, Quadlet ist enthalten
```

**Port 80 rootless freigeben.** Die API erlaubt per CORS nur die Origin `http://APP_HOSTNAME` ohne
Port. Die App muss deshalb auf Port 80 laufen (HTTPS später auf 443). Rootless darf das standardmäßig
nicht:

```sh
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-weiss-ports.conf
sudo sysctl --system
```

Das gilt für alle Benutzer des Rechners. Alternative: Portweiterleitung 80 → hochgelegener Port
per nftables/iptables.

**Firewall.** Erlaube eingehend TCP 80, 8000 und 8080 (HTTP-Modus). Eine Firewall kann außerdem
EPICS-CA-Antworten (UDP) blockieren.

## Variante A: Schnellstart mit `podman compose`

```sh
cp .env.example .env          # anpassen, siehe Demo-Modus unten
podman compose build
podman compose up -d
```

**Achtung:** Das Frontend-Image bekommt `VITE_DEMO_MODE` beim Bauen aus `DEMO_MODE` in der `.env`.
Fehlt die Datei oder der Wert, baut Compose mit `false`, und die Demo-Buttons fehlen (siehe
[Demo-Modus](#demo-modus-und-anmeldung)). Prüfe die `.env` vor dem Bauen.

Aufruf: `http://localhost` (bzw. `http://<APP_HOSTNAME>`). Mit `podman compose down` stoppst du alles.

## Variante B: Dauerbetrieb als systemd-Dienst (rootless)

Quadlet-Units laufen im Benutzerkontext. Die Images baut `scripts/build-images.sh`, weil Quadlet
`.build`-Dateien erst ab Podman 5.2 kennt (Ubuntu 24.04 hat 4.9).

```sh
scripts/install.sh                          # Units nach ~/.config/containers/systemd, Config nach ~/.config/weiss
nano ~/.config/weiss/weiss.env              # DEMO_MODE, APP_HOSTNAME, EPICS-Variablen ...
scripts/build-images.sh                     # baut localhost/weiss, -api, -epicsws
systemctl --user enable --now weiss.service # zieht weiss-api und weiss-epicsws nach
loginctl enable-linger "$USER"              # Start beim Booten ohne Login, läuft nach Logout weiter
```

Kontrolle:

```sh
systemctl --user status weiss weiss-api weiss-epicsws
journalctl --user -u weiss-epicsws -f
podman ps
```

Die Unit-Namen entstehen aus den Quadlet-Dateinamen. Mit `systemctl --user daemon-reload` werden
geänderte Units neu eingelesen. Bei Fehlern zeigt
`/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun` die erzeugten Units
samt Fehlermeldungen.

**Update auf eine neue Upstream-Version:**

```sh
WEISS_REF=v1.2.3 scripts/build-images.sh    # Branch, Tag oder Commit; Standard: main
systemctl --user restart weiss-api weiss-epicsws weiss
```

## EPICS Channel Access (lokal)

`weiss-epicsws` läuft im **Host-Netzwerk**. Das funktioniert rootless und ist nötig, damit
Channel Access (UDP-Suche und Broadcast, TCP 5064) wie auf dem Host arbeitet. Ohne Host-Netzwerk
kämen CA-Broadcasts im rootless Bridge-Modus nicht durch.

| Variable | Wert hier | Bedeutung |
|---|---|---|
| `EPICS_DEFAULT_PROTOCOL` | `ca` | Protokoll für PV-Namen ohne Präfix (`ca://` oder `pva://`). Upstream-Standard ist `pva`. |
| `EPICS_CA_ADDR_LIST` | `localhost` | Lokale IOCs. Für IOCs in anderen Netzen Host oder Broadcast-Adresse ergänzen. |
| `EPICS_CA_AUTO_ADDR_LIST` | `YES` | Zusätzlich die Broadcast-Adressen der Host-Interfaces nutzen. |
| `EPICS_CA_MAX_ARRAY_BYTES` | `1000000` | Maximale Arraygröße. Für große Waveforms erhöhen. |
| `EPICS_PVA_*` | `localhost` / `YES` | Wie CA, für PV Access. |
| `EPICS_MAX_UPDATE_RATE_HZ` | `30` | Max. Update-Rate pro PV an Clients (`0` = ungedrosselt). |
| `EPICS_MAX_CLIENT_QUEUE` | `1000` | Zu langsame Clients werden getrennt. |

Rootless ändert an diesen Variablen nichts. Entscheidend ist nur das Host-Netzwerk.

**Wichtig beim Start:** Ohne `--env-file` nimmt der Container die Upstream-Standards, also
`EPICS_DEFAULT_PROTOCOL=pva`. Die Brücke liefert dann CA-Werte mit Präfix (`ca://WEISS:TEST:COUNTER`).
Starte deshalb immer mit `--env-file ~/.config/weiss/weiss.env` (siehe Variante B).


**Test mit einem vorhandenen IOC auf dem Host:** `caget MY:PV` muss dort funktionieren. Im
WEISS-Editor ein Widget mit dem PV-Namen `MY:PV` (oder `ca://MY:PV`) anlegen und in den
Runtime-Modus wechseln. Logs: `podman logs weiss-epicsws`.

### Test-SoftIOC mit Testvariablen (optional)

`softioc/` enthält eine SoftIOC aus **EPICS Base 7.0.9** (CA und PVA), die du ohne eigenen IOC
zum Testen nutzen kannst. Sie läuft wie `weiss-epicsws` im Host-Netzwerk, damit beide sich über
`localhost` finden. Das Image wird beim ersten Mal aus dem Quellcode gebaut und braucht dafür einige
Minuten. Eine andere EPICS-Base-Version setzt du mit dem `ARG EPICS_BASE_REF` in
`softioc/Containerfile`.

| PV | Typ | Beschreibung |
|---|---|---|
| `WEISS:TEST:COUNTER` | calc | Zähler 0..99, 2 Hz |
| `WEISS:TEST:SINE` | calc | Sinus 0..100, folgt dem Zähler |
| `WEISS:TEST:SETPOINT` | ao | **schreibbar**, 0..100 V (der Treiber begrenzt auf 0..100) |
| `WEISS:TEST:READBACK` | calc | Istwert, folgt dem Sollwert sofort |
| `WEISS:TEST:SWITCH` | bo | **schreibbar**, Aus/Ein |
| `WEISS:TEST:STATUS` | bi | Status, folgt dem Schalter |
| `WEISS:TEST:MESSAGE` | stringout | **schreibbar**, Text |
| `WEISS:TEST:WAVE` | waveform | Array mit 10 Werten (Quadratzahlen) |

Eigene Variablen ergänzt du in `softioc/test.db` (danach Image neu bauen).

**Start mit Compose:** der Dienst `weiss-softioc` ist in `compose.yaml` enthalten.

```sh
podman compose build weiss-softioc
podman compose up -d weiss-softioc
```

**Start als systemd-Dienst:**

```sh
scripts/install.sh --with-softioc
scripts/build-images.sh --with-softioc
systemctl --user enable --now softioc.service
```

**Lesen und Schreiben prüfen** (`caget`/`caput` sind im Image enthalten):

```sh
podman exec weiss-softioc caget WEISS:TEST:COUNTER WEISS:TEST:SETPOINT
podman exec weiss-softioc caput WEISS:TEST:SETPOINT 42.5
podman exec weiss-softioc caget WEISS:TEST:READBACK        # folgt dem Sollwert: 42.5
podman exec weiss-epicsws python -c "import epics; print(epics.caget('WEISS:TEST:SINE'))"
```

Im WEISS-Editor Widgets mit diesen PV-Namen anlegen und in den Runtime-Modus wechseln, dann
siehst du die Werte und kannst `SETPOINT`, `SWITCH` und `MESSAGE` schreiben.

**Fertiges Beispieldisplay:** `examples/weiss-test.bob` zeigt alle Test-PVs. Import im Editor über
**Import → From CSS/Phoebus** (eingeloggt als Developer, neue Datei anlegen). Die Datei nutzt nur
Widgets, die der Importer unterstützt. Prüfe danach die Warnungen und die Layouts im Editor.

### PV-Brücke über den WebSocket prüfen

`scripts/check-ws.py` verbindet sich mit `weiss-epicsws` auf Port 8080, wie es der Browser tut,
und liest `WEISS:TEST:COUNTER`. Mit `--write` schreibt es außerdem `WEISS:TEST:SETPOINT = 42.5`
und wartet, bis der Wert über das Abo zurückkommt. Es braucht keine Anmeldung.

```sh
python3 -m venv ~/weiss-check && ~/weiss-check/bin/pip install websockets
~/weiss-check/bin/python scripts/check-ws.py ws://localhost:8080
~/weiss-check/bin/python scripts/check-ws.py ws://localhost:8080 --write
```

Erwartet wird jeweils `OK: …` und Exit-Code 0. Die Werte kommen mit Präfix (`ca://`) oder ohne an;
das Skript akzeptiert beides.

Läuft zusätzlich ein IOC auf dem Host, teilen sich beide UDP-Port 5064. Die Suche per Broadcast
erreicht beide (`EPICS_CA_AUTO_ADDR_LIST=YES`). Für eine eindeutige Adressierung kannst du der
Test-IOC einen eigenen Port geben (`Environment=EPICS_CA_SERVER_PORT=5164` in der Unit) und
`localhost:5164` in `EPICS_CA_ADDR_LIST` ergänzen.

### Stresstest mit 1000 PVs

Die Test-SoftIOC enthält 1000 Kanäle unter `WEISS:STRESS:*`, die im gleichen Takt Updates senden
(Rate einstellbar bis 10 Hz = 10 000 Updates/s), und es gibt ein passendes WEISS-Display. Bei 2 Hz
läuft die Kette stabil, bei 5 Hz staut sich `weiss-epicsws`. Aufbau, Display, Messmethoden und
Ergebnisse stehen in der **[Anleitung zum Stresstest](docs/stresstest.md)**.

```sh
podman compose build weiss-softioc && podman compose up -d weiss-softioc
~/weiss-check/bin/python scripts/check-ws-stress.py --rate 2 --duration 20
```

## API prüfen

Die API hat keine Weboberfläche außer der Swagger-Doku unter `/docs` (FastAPI-Standard, im Code
`backend/api/src/api/main.py`). Zwei Befehle prüfen, ob sie läuft und die Sitzungsprüfung arbeitet:

```sh
# Lebt die API? Erwartet: 200
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/docs

# Sitzung ohne Cookie. Erwartet: 401 und {"detail":"Not authenticated"}
curl -s -w "\n%{http_code}\n" http://localhost:8000/api/v1/auth/me
```

`000` bedeutet, dass auf Port 8000 nichts antwortet. Dann läuft der Container `weiss-api` nicht:
`podman ps -a --filter name=weiss-api` und `podman logs weiss-api`. Der zweite Befehl ist der
wichtigere Test, denn genau diesen Endpunkt nutzt später die Sitzungsprüfung (`auth_request`).

## Demo-Modus und Anmeldung

`DEMO_MODE` wirkt an **zwei Stellen** und muss dort denselben Wert haben:

| Stelle | Variable | Wirkung | Wann wirksam |
|---|---|---|---|
| Frontend | `VITE_DEMO_MODE` (aus `DEMO_MODE`) | Zeigt die Demo-Login-Buttons. `VITE_AUTH_IDENTITY_PROVIDER` (aus `AUTH_IDENTITY_PROVIDER`) zeigt den Button für den echten Login. | **Beim Bauen** fest eingebacken, Änderung braucht Rebuild |
| API | `DEMO_MODE` | `true`: nur der Demo-Provider ist aktiv, andere Logins werden mit 403 abgelehnt, OAuth wird beim Start nicht eingerichtet (`AUTH_CLIENT_*` nicht nötig). `false`: Demo-Login wird mit 403 abgelehnt, OAuth ist Pflicht. | Beim Start des Containers |

Daraus folgt:

- **`DEMO_MODE=true` bedeutet keine echte Authentifizierung.** Beim Demo-Login wählt man die Rolle
  selbst (Developer oder Operator). Jeder, der die Seite erreicht, kann als Developer Dashboards
  ändern und über `TECHNICAL_ACCOUNT_TOKEN` committen. Nutze das nur lokal oder im geschützten Netz.
- **Wechsel des Modus = Rebuild plus Neustart.** Nur die Variable zu ändern, reicht nicht. Sonst
  passen Buttons und Backend nicht zusammen und der Login schlägt mit 403 fehl.
  - Compose: `podman compose build && podman compose up -d`
  - Quadlet: `scripts/build-images.sh && systemctl --user restart weiss-api weiss-epicsws weiss`
- Sowohl `compose.yaml` als auch `scripts/build-images.sh` übergeben `DEMO_MODE` und
  `AUTH_IDENTITY_PROVIDER` aus deiner Konfiguration ans Frontend-Build. Pflege sie daher nur in
  `.env` bzw. `~/.config/weiss/weiss.env`.

**Symptom: Login-Seite zeigt nur „Organization account“.** Das Frontend wurde mit
`VITE_DEMO_MODE` ungleich `true` gebaut. Die API läuft aber mit `DEMO_MODE=true`, deshalb würde
der Organisations-Login mit 403 scheitern. Lösung: Frontend-Image mit den passenden Werten neu bauen.

```sh
podman rm -f weiss
podman build --target prod \
  --build-arg VITE_DEMO_MODE=true --build-arg VITE_AUTH_IDENTITY_PROVIDER=oauth \
  -t localhost/weiss:latest https://github.com/weiss-controls/weiss.git#main
podman run -d --name weiss -p 80:8081 --env-file ~/.config/weiss/weiss.env localhost/weiss:latest
```

Die Demo-Rollen sind danach „Demo Operator“ und „Demo Developer“. Der Developer-Login funktioniert
ohne `TECHNICAL_ACCOUNT_TOKEN`, aber Commits und Git-Funktionen nicht.

### Von Demo auf echten Login (OAuth2/OIDC) umstellen

1. Bei deinem Identity Provider einen Client registrieren (Anleitung:
   [Organization credentials](https://docs.weiss-controls.org/)) mit der Redirect-URI deiner App.
2. In der Konfiguration setzen:
   ```sh
   DEMO_MODE=false
   AUTH_IDENTITY_PROVIDER=oauth
   AUTH_ISSUER=https://idp.example.com/realms/xyz
   AUTH_CLIENT_ID=...
   AUTH_CLIENT_SECRET=...
   ```
3. Images neu bauen und Dienste neu starten (siehe oben).
4. Benutzer der Developer-Rolle in `roles.toml` eintragen.

### Benutzerrollen

Wer in `roles.toml` unter `[roles] developers = [...]` steht, hat die Developer-Rolle, alle anderen
sind Operator. Für Quadlet liegt die aktive Datei unter `~/.config/weiss/roles.toml`. Der
Demo-Login ignoriert diese Datei. Änderungen gelten nach einem API-Neustart.

### Git-Anbindung

Für Commit und Push aus dem Editor braucht die API einen Personal Access Token mit
Schreibrechten in `TECHNICAL_ACCOUNT_TOKEN`. Name und E-Mail für die Commits setzt du über
`TECHNICAL_ACCOUNT_USERNAME` und `TECHNICAL_ACCOUNT_EMAIL`. Die Daten liegen im Volume `weiss-storage`
(Compose: `storage`).

## Später auf HTTPS umsteigen

HTTPS wird komplett von nginx im Container `weiss` erledigt. Das Frontend wird dafür **nicht neu
gebaut**. Es wählt anhand des Protokolls im Browser automatisch `/api/` und `/ws/` über nginx statt
der direkten Ports.

1. **Zertifikat bereitstellen** (PEM, Full-Chain und Schlüssel), z. B. von eurer IT. Zum Testen
   ein selbstsigniertes:
   ```sh
   mkdir -p ~/.config/weiss/certs && cd ~/.config/weiss/certs
   openssl req -x509 -newkey rsa:4096 -keyout privkey.pem -out fullchain.pem \
     -days 365 -nodes -subj "/CN=mein-server"
   ```
2. **Leserechte für nginx.** Der Prozess im Container läuft als UID 101. Rootless wird diese UID
   auf eine Sub-UID abgebildet, deshalb:
   ```sh
   podman unshare chown 101:101 ~/.config/weiss/certs/privkey.pem ~/.config/weiss/certs/fullchain.pem
   chmod 640 ~/.config/weiss/certs/privkey.pem
   ```
3. **Port 443 rootless freigeben.** Der Sysctl-Wert aus den Voraussetzungen (`80`) deckt 443 mit ab.
   Der Browser nutzt Port 443 ohne Portangabe in der URL.
4. **Konfiguration ändern** (`weiss.env` bzw. `.env`):
   ```sh
   ENABLE_HTTPS=true
   APP_HOSTNAME=mein-server        # exakt der Name, unter dem der Browser die Seite aufruft
   ```
   `ENABLE_HTTPS` bestimmt auch das Schema der CORS-Origin und setzt das `Secure`-Flag der
   Session-Cookies. Bei OAuth muss die Redirect-URI beim Identity Provider auf `https://` lauten.
5. **Quadlet: `quadlet/weiss.container` ergänzen** (und nach `~/.config/containers/systemd/`
   kopieren, bzw. `scripts/install.sh` erneut ausführen):
   ```ini
   PublishPort=443:8082
   Volume=%h/.config/weiss/certs/fullchain.pem:/etc/nginx/certs/fullchain.pem:ro
   Volume=%h/.config/weiss/certs/privkey.pem:/etc/nginx/certs/privkey.pem:ro
   ```
   Der bestehende `PublishPort=80:8081` bleibt. Im HTTPS-Modus leitet nginx dort per 301 auf HTTPS
   um.

   **Compose:** in `compose.yaml` beim Dienst `weiss` `ENABLE_HTTPS: "false"` durch
   `${ENABLE_HTTPS:-false}` ersetzen und dasselbe bei `weiss-api` tun. Außerdem ergänzen:
   ```yaml
   ports:
     - "443:8082"
   volumes:
     - ${SSL_CERT_FILE}:/etc/nginx/certs/fullchain.pem:ro
     - ${SSL_KEY_FILE}:/etc/nginx/certs/privkey.pem:ro
   ```
6. **Neu starten.** Ein Rebuild ist nicht nötig:
   ```sh
   systemctl --user daemon-reload
   systemctl --user restart weiss-api weiss
   ```
   (Compose: `podman compose up -d`.)
7. **Aufräumen (optional).** Die Direktports 8000 und 8080 werden im HTTPS-Modus vom Browser nicht
   mehr genutzt. `weiss-api` kann dann auf `PublishPort=127.0.0.1:8000:8000` beschränkt oder ganz
   unveröffentlicht bleiben, und in der Firewall genügen 80 und 443. `weiss-epicsws` muss weiterhin
   auf dem Host erreichbar bleiben, weil nginx es über `host-gateway` anspricht. Port 8080 muss
   dafür von außen nicht offen sein, nur lokal erreichbar.

## Fehlersuche

| Symptom | Ursache und Lösung |
|---|---|
| `bind: permission denied` auf Port 80 | Sysctl `ip_unprivileged_port_start` nicht gesetzt (siehe Voraussetzungen). |
| Login oder API-Aufrufe schlagen im Browser mit CORS-Fehler fehl | Seite wird nicht über `http://<APP_HOSTNAME>` auf Port 80 aufgerufen oder `APP_HOSTNAME` passt nicht zur URL. |
| Login-Seite zeigt nur „Organization account“ | Frontend mit `VITE_DEMO_MODE` ≠ `true` gebaut. Neu bauen, siehe [Demo-Modus](#demo-modus-und-anmeldung). |
| `curl` auf Port 8000 liefert `000` | Container `weiss-api` läuft nicht. `podman logs weiss-api`. |
| Login: „Only demo provider…“ / „Demo mode is not enabled“ (403) | `DEMO_MODE` in Frontend-Build und API stimmen nicht überein. Rebuild und Neustart. |
| PVs bleiben leer | `podman logs weiss-epicsws`. IOC mit `caget` auf dem Host testen, `EPICS_CA_ADDR_LIST` prüfen, Firewall (UDP/TCP 5064). |
| WebSocket verbindet nicht (HTTP) | Port 8080 vom Browser aus nicht erreichbar (Firewall) oder `weiss-epicsws` läuft nicht. |
| HTTPS: nginx startet nicht / Schlüssel nicht lesbar | Dateirechte (Schritt 2), Pfade der Volumes. |
| HTTPS: `/ws/` liefert 502 | `weiss` erreicht `weiss-epicsws` nicht über `host-gateway`. Podman-Version prüfen, `podman exec weiss getent hosts weiss-epicsws`. |
| Dienste starten nach Reboot nicht | `loginctl enable-linger "$USER"` fehlt. |
