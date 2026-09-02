# 03 – Production Server

Stand der zuletzt verifizierten Serverprüfung: 2. September 2026

## Serversteckbrief

| Merkmal | Verifizierter Wert |
| --- | --- |
| Provider | DigitalOcean Droplet |
| Region | `fra1` |
| Hostname | `ubuntu-s-1vcpu-1gb-fra1-01` |
| öffentliche IPv4 | `138.68.87.128` |
| Betriebssystem | Ubuntu 24.04.3 LTS |
| Kernel | 6.8.0-138-generic |
| CPU/RAM/Disk | 1 vCPU, ca. 961 MB RAM, 24 GB Root-Disk |
| Server-Zeitzone | `Etc/UTC` |
| fachliche Zeitzone | `Europe/Zurich` |
| Docker/Compose | Docker 29.2.1, Compose 5.1.0 beim Audit |
| Produktionspfad | `/opt/anny_webhook` |
| Domain | `webhook.voltabreau.ch` |

Versionen sind eine Momentaufnahme. Vor Wartung immer erneut read-only prüfen.

## Netzwerk und Firewall

UFW war aktiv. Öffentlich freigegeben waren:

| Port | Protokoll | Dienst |
| ---: | --- | --- |
| 22 | TCP | SSH |
| 80 | TCP | Caddy HTTP/ACME/Redirect |
| 443 | TCP | Caddy HTTPS |

Port 8099 wird nur mit Compose `expose` im internen Docker-Netz bereitgestellt, nicht auf dem Host veröffentlicht. Es darf keine zusätzliche öffentliche 8099-Freigabe geben.

DigitalOcean Cloud Firewall oder weitere Providerregeln konnten nicht über ein Teamkonto verifiziert werden.

**TODO – vor finaler Übergabe verifizieren:** DigitalOcean Firewall-/VPC-Regeln im Control Panel sowie aktueller UFW-Status erneut erfassen.

## SSH-Zugang

Der Audit bestätigte aktuell:

- `PermitRootLogin yes`
- `PasswordAuthentication yes`
- `PubkeyAuthentication yes`
- `MaxAuthTries 6`

Das ist ein offener Härtungspunkt. Bis ein neuer namentlicher Admin-Key und der Provider-Recoveryweg getestet sind, darf der bestehende Zugang nicht vorschnell deaktiviert werden. Zielzustand und Reihenfolge stehen in [10_SECURITY_AND_SECRETS.md](10_SECURITY_AND_SECRETS.md).

**TODO – vor finaler Übergabe verifizieren:** Fingerprint, Kommentar und organisatorischer Owner jedes Eintrags in `authorized_keys`; Existenz weiterer sudo-/Wartungsbenutzer.

## Verzeichnisstruktur

| Pfad | Inhalt | Git-rekonstruierbar? |
| --- | --- | --- |
| `/opt/anny_webhook/app.py` | Anwendung | ja |
| `/opt/anny_webhook/templates/` | Dashboard-Template | ja |
| `/opt/anny_webhook/Dockerfile` | Allocator-Image | ja |
| `/opt/anny_webhook/docker-compose.yml` | produktive Compose-Datei; entspricht Repository `docker-compose.production.yml` | ja |
| `/opt/anny_webhook/Caddyfile` | Reverse Proxy | ja |
| `/opt/anny_webhook/.env` | Konfiguration und Secrets, Modus `0600` beim Audit | **nein** |
| `/opt/anny_webhook/data/allocator.db` | produktive SQLite-Datenbank | **nein** |
| `/opt/anny_webhook/backups/` | lokale Vorher-/Datenbanksicherungen | **nein**, gleicher Droplet |
| `/opt/anny_webhook/releases/` | beim manuellen Release verwendete Stagingstände | Bestand/Aufbewahrung erneut prüfen |

## Docker-Topologie

| Container | Image/Quelle | Ports | Mounts/Volumes | Restart | Health |
| --- | --- | --- | --- | --- | --- |
| `anny_webhook-allocator-1` | lokal aus Repository gebaut; OCI-Revision `6937aa89...` | 8099 nur intern | `./data:/data` | `unless-stopped` | HTTP `/health`, 30 s, 5 s Timeout, 3 Retries |
| `anny_webhook-caddy-1` | `caddy:2` | Host 80/443 | `Caddyfile` read-only, `caddy_data`, `caddy_config` | `unless-stopped` | kein eigener Compose-Healthcheck |

Allocator-Härtung in Compose:

- read-only Root-Dateisystem
- `/tmp` als tmpfs
- `no-new-privileges:true`
- Init-Prozess aktiviert
- JSON-Logrotation: maximal 10 MB, 3 Dateien pro Container

Der Allocator benötigt genau einen Worker/eine aktive Instanz. Mehrere Container oder Worker sind ohne verteilte Sperre unsicher.

## SQLite

- Hostpfad: `/opt/anny_webhook/data/allocator.db`
- Containerpfad: `/data/allocator.db`
- Connection-Timeout und `PRAGMA busy_timeout`: 30 Sekunden
- Tabellen: `allocations`, `webhook_events`
- nach Release 3.1.0: `PRAGMA integrity_check = ok`, 773 Allocations, 767 assigned, 6 unassigned, 0 erkannte Tischkollisionen, 0 retry-fähige Webhook-Fehler der letzten 24 Stunden

Die Zahlen ändern sich laufend. Sie dienen nur als Referenz, nicht als Sollwert.

## Caddy und TLS

Die produktive Konfiguration ist minimal:

```caddyfile
webhook.voltabreau.ch {
  reverse_proxy allocator:8099
}
```

Caddy beschafft und erneuert TLS-Zertifikate automatisch. Das am 1. September 2026 geprüfte Let's-Encrypt-Zertifikat war gültig vom 28. August bis 26. November 2026. Die automatische Erneuerung hängt von laufendem Caddy, korrektem DNS und erreichbaren Ports 80/443 ab.

## Restart-Verhalten

- Beide Container verwenden `restart: unless-stopped` und starten nach Docker-/Serverneustart wieder, sofern sie nicht ausdrücklich gestoppt wurden.
- Caddy wartet beim Compose-Start auf den gesunden Allocator.
- Ein abstürzender Allocator wird neu gestartet; wiederholte Restarts werden derzeit nicht extern alarmiert.
- Uvicorn läuft mit einem Worker und ohne Access-Log.

## Logs

Sichere Standardabfragen:

```bash
cd /opt/anny_webhook
docker compose ps
docker compose logs --tail=200 allocator
docker compose logs --tail=200 caddy
docker inspect --format '{{.RestartCount}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' anny_webhook-allocator-1
journalctl -u docker --since '2 hours ago' --no-pager
```

Keine vollständigen Webhook-Payloads, Authorization-Header oder Query-Strings in Tickets kopieren. Die historische Webhook-URL enthält ein Secret im Query-Parameter; `docker compose logs` deshalb nur geschützt behandeln.

## Healthchecks

- öffentlich: `https://webhook.voltabreau.ch/health`
- intern aus dem Docker-Netz/Container: `http://127.0.0.1:8099/health`
- erwartete Felder: `ok=true`, `database=true`, `version=3.1.0`, UTC-Zeitstempel

Der Endpoint prüft eine SQLite-Abfrage. Er prüft nicht die Anny API, Webhook-Zustellung, Disk Space, Backups, DNS oder Tischkollisionen.

## Server kennenlernen in 10 Minuten

Alle folgenden Befehle sind read-only. Sie verändern weder Container noch Datenbank.

```bash
ssh root@138.68.87.128

hostnamectl
timedatectl
uptime
free -h
df -h /

cd /opt/anny_webhook
pwd
ls -ld . data backups
stat -c '%a %U:%G %n' .env data/allocator.db

docker version
docker compose version
docker compose ps
docker compose images
docker inspect --format '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}} readonly={{.HostConfig.ReadonlyRootfs}}' anny_webhook-allocator-1
docker inspect --format '{{json .Mounts}}' anny_webhook-allocator-1

curl --fail --silent --show-error https://webhook.voltabreau.ch/health
docker compose logs --tail=50 allocator
docker compose logs --tail=50 caddy

ufw status numbered
ss -lntp
exit
```

Nicht mit `cat .env`, `env`, `docker inspect` ohne gezieltes Format oder vollständigem Prozessdump arbeiten, wenn Ausgabe in Chat/Ticket landen könnte; diese Befehle können Secrets offenlegen.

## Sichere SQLite-Diagnose ohne Schreibzugriff

```bash
cd /opt/anny_webhook
docker compose exec -T allocator python -c "import sqlite3; c=sqlite3.connect('file:/data/allocator.db?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print(c.execute('SELECT status, count(*) FROM allocations GROUP BY status').fetchall()); c.close()"
```

Für Buchungsdetails bevorzugt Dashboard oder gezielte, datensparsame Queries verwenden. Kundendaten und vollständige Notizen gehören nicht in Tickets.

## Noch zu verifizieren

- TODO – vor finaler Übergabe verifizieren: heutige Disk-Auslastung, Container-Restartzähler und Docker-Imagebestand
- TODO – vor finaler Übergabe verifizieren: Cron-/systemd-Timer, DigitalOcean-Agent, Fail2ban und externe Monitoringagenten
- TODO – vor finaler Übergabe verifizieren: Zuordnung aller SSH-Keys und Benutzer
- TODO – vor finaler Übergabe verifizieren: automatisierte DigitalOcean-Droplet-Backups im Providerkonto
- TODO – vor finaler Übergabe verifizieren: Bestand und Integrität aller aktuellen lokalen Backups
