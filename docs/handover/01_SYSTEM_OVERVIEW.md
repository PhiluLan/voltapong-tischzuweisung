# 01 – System Overview

Stand: 1. September 2026

## Systemauftrag

Der Dienst erhält relevante Buchungsereignisse von Anny, lädt die Buchung über die Anny-API, berechnet eine konfliktfreie Zuordnung zu acht physischen Tischlabels, speichert diese abgeleitete Belegung in SQLite und schreibt die Tischangabe nach Anny zurück. Das Dashboard stellt einen lesenden Betriebsstatus bereit.

Anny bleibt das führende System für Buchung, Zeitraum, Status, Service und Kundenkommunikation. SQLite ist für den laufenden Allocator trotzdem betriebsnotwendig: Sie enthält den bisher berechneten Tisch- und Idempotenzzustand. Ein Verlust lässt sich mit der aktuellen Anwendung nicht vollständig automatisch aus Anny rekonstruieren.

Die fachliche Logik einschließlich Storno, Reconciliation und Nachverteilung steht in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Verifiziertes Laufzeitbild

```text
Gast/Mitarbeiter
      │
      ▼
    Anny ── HTTPS Webhook ──► webhook.voltabreau.ch:443
      ▲                               │
      │                               ▼
      └──── Anny API GET/PATCH ── Allocator (Docker, Port 8099 intern)
                                      │
                                      ├── SQLite /data/allocator.db
                                      └── Dashboard/API

Internet :80/:443 ──► Caddy (Docker) ──► allocator:8099
Entwickler ── SSH :22 ──► Ubuntu/Docker unter /opt/anny_webhook
GitHub ── manueller Release-Prozess ──► Produktionsserver
```

## Komponenten und Grenzen

| Komponente | Verantwortlich für | Nicht verantwortlich für |
| --- | --- | --- |
| Anny | Buchung, Status, Ressource, Service, Zeitraum, Kundenkommunikation | konkrete lokale Tischkollisionen |
| Anny-Webhook | Zustellung create/update/delete | vollständiger Buchungsinhalt; dieser wird per API nachgeladen |
| Allocator | Authentifizierung, Idempotenz, Zuweisung, Storno/Freigabe, Rückschreiben | Benutzerverwaltung, vollständigen periodischen Anny-Abgleich |
| SQLite | Allocations und `event_id`-Ergebnisse | primäre Buchungsquelle, Offsite-Sicherung |
| Dashboard | lesender SQLite-/Webhook-Status | vollständige Anny-Erreichbarkeits- oder Backup-Prüfung |
| Caddy | TLS, Port 80/443, Reverse Proxy | Anwendungslogik |
| Docker Compose | Container, Mounts, Healthcheck, Restart, Logrotation | Release-Automation und Offsite-Backup |
| GitHub | Code, Tests, Dokumentation | automatisches Deployment; derzeit gibt es keine CI/CD-Workflowdatei |

## Verifizierte Produktionsdaten

| Merkmal | Wert |
| --- | --- |
| öffentliche Domain | `webhook.voltabreau.ch` |
| Produktions-IP | `138.68.87.128` |
| Provider/Region | DigitalOcean Droplet, `fra1` |
| Produktionspfad | `/opt/anny_webhook` |
| Datenbank | `/opt/anny_webhook/data/allocator.db` |
| Container | `anny_webhook-allocator-1`, `anny_webhook-caddy-1` |
| Anwendungsversion | 3.0.0 |
| produktiver Code-Commit | `c261d029d8929582aa8d0628267c79003e0093be` |
| fachliche Zeitzone | `Europe/Zurich` |
| Server-Zeitzone | UTC/`Etc/UTC` |

Am Prüfzeitpunkt waren die produktionsrelevanten Dateien zwischen Commit `c261d029...` und dem damaligen Repository-`main` inhaltlich unverändert. Spätere Dokumentationscommits sind nicht automatisch auf Produktion ausgerollt.

## Wichtige Laufzeitannahmen

1. Genau **ein** Allocator-Prozess beziehungsweise Uvicorn-Worker und genau eine aktive Allocator-Instanz. Die Sperre gegen gleichzeitige Auswahl ist nur pro Prozess vorhanden.
2. Das bind-mount `./data:/data` muss auf die bestehende Produktionsdatenbank zeigen. Ein leeres `data/` würde eine neue, leere Datenbank erzeugen.
3. Anny-API-Zugriff benötigt `b.bookings:read` und `b.bookings:update`.
4. `ALLOCATE_RESOURCE_IDS=181227` begrenzt die Integration auf „Ping Pong Tisch“.
5. Das Webhook-Secret wird historisch als Query-Parameter akzeptiert. Deshalb bleibt Uvicorn ohne Access-Log, bis auf Header-/Signaturauthentifizierung migriert wurde.
6. Fachliche Kapazitätsfehler werden mit HTTP 200 als `unassigned` verarbeitet; temporäre Anny-/Patchfehler liefern HTTP 503 und bleiben retry-fähig.

## Daten, die nicht aus Git rekonstruierbar sind

- aktuelle `allocator.db` einschließlich Zuweisungen und Event-Idempotenz
- Produktions-`.env` und alle Secrets
- Account-/MFA-/Recovery-Informationen der Provider
- aktueller Caddy-Zertifikatscache; dieser ist bei korrektem DNS grundsätzlich neu erzeugbar
- Provider-/Billing-Konfiguration
- nicht versionierte Provider-Monitoring- oder Backup-Einstellungen

## Bekannte Konsistenzgrenzen

- Es gibt keinen vollständigen periodischen Import aller Anny-Buchungen.
- `/health` prüft Prozess und SQLite-Lesezugriff, nicht Anny, DNS, Webhook-Zustellung, Disk Space oder Backup-Erfolg.
- Historische `unassigned`-Einträge können das Dashboard gelb färben.
- „8/8“ in Anny ist bei gemischtem Tischbedarf nicht zwingend identisch mit acht erfolgreich zugewiesenen physischen Tischlabels. Details: [07_ANNY_CONFIGURATION.md](07_ANNY_CONFIGURATION.md#bekannte-kapazitätsproblematik).
- SQLite ist lokal persistent, aber derzeit ist kein automatisches, verifiziertes Offsite-Backup nachgewiesen.

## Kritische Abhängigkeiten

| Abhängigkeit | Auswirkung bei Ausfall |
| --- | --- |
| Anny API/Webhooks | neue oder geänderte Buchungen werden nicht zuverlässig zugeordnet |
| Droplet | Webhook, Dashboard und SQLite nicht verfügbar |
| SQLite | keine verlässliche lokale Belegung/Idempotenz |
| Domain/DNS/TLS | Anny und Dashboard erreichen Caddy nicht |
| Anny-Token | Buchungen können weder geladen noch aktualisiert werden |
| Webhook-Secret | Zustellungen werden abgewiesen oder der Endpunkt wäre ungeschützt |
| organisatorische Accounts | kein Betrieb, Billing, Recovery oder Offboarding ohne Philipp möglich |

## Status nach Risikoklasse

### HANDOVER BLOCKER

- Organisations-Ownership und Recovery für GitHub, DigitalOcean, Domain/DNS, Anny und Billing sind nicht vollständig nachgewiesen.
- Kein verifiziertes Offsite-Backup und kein vollständiger Restore-/Droplet-Rebuild durch eine zweite Person.
- Kein verifizierter organisatorischer Secret-Manager als unabhängige Quelle.
- SQLite kann nach Totalverlust nicht vollständig automatisch aus Anny rekonstruiert werden.

### HIGH PRIORITY

- Root- und Passwort-SSH sind aktiv; persönlicher, eingeschränkter Wartungszugang und Break-glass-Prozess fehlen.
- Externes Monitoring und Alarmempfänger sind nicht verifiziert.
- Aktiver alter, überberechtigter Anny-Token muss nach Abschluss der Übergabetests widerrufen werden.
- Deployment und Rollback sind manuell und noch nicht von einem Nachfolger geprobt.

### RECOMMENDED

- CI für Tests und reproduzierbare, unveränderliche Images.
- Periodischer Anny↔SQLite-Bestandsabgleich.
- Persönliche Dashboard-Anmeldung statt gemeinsamem Basic-Auth-Konto.

### OPTIONAL

- Migration auf eine Managed-Plattform/PostgreSQL, falls der eigene Serverbetrieb organisatorisch unerwünscht wird. Sie ist für die heutige Last nicht technisch erforderlich.
