# 09 – Monitoring

Stand: 1. September 2026

## Kurzurteil

Lokale Zustandsanzeigen und begrenzte Logs sind vorhanden. Ein unabhängiges Monitoring mit Alarmempfängern, Disk-/Restart-/Backupalarm und nachweisbarem Eskalationsweg ist nicht verifiziert.

**HANDOVER BLOCKER:** Niemand kann derzeit anhand der verifizierten Konfiguration garantieren, dass ein Ausfall, fehlgeschlagenes Backup oder wiederholter Webhookfehler zeitnah bei einer von Philipp unabhängigen Person ankommt.

## Bereits vorhanden

| Signal | Was es prüft | Grenze |
| --- | --- | --- |
| öffentliches `/health` | App antwortet und `SELECT 1` auf SQLite funktioniert | kein Anny, DNS-Ursachenanalyse, Disk, Backup oder Kollision |
| Docker Health des Allocators | interner HTTP-Health alle 30 Sekunden | kein externer Alarm; Caddy hat keinen Compose-Healthcheck |
| `restart: unless-stopped` | Container startet nach Fehler/Hoststart neu | behebt Ursache nicht; kein Restartalarm |
| Dashboard | zukünftige offene Zuweisungen, ungültige Daten, Kollisionen, retry-fähige Events, Aktivität | nur bei manuellem Öffnen; kein vollständiger Anny-Abgleich |
| Docker JSON Logs | Allocator-/Caddy-Ausgaben, lokal rotiert 10 MB × 3 | kein zentraler Speicher/Alarm; datenschutzsensitiv |
| Anny Call History | Zustellversuche und HTTP-Status | nur in Anny sichtbar; Fehlerzähler beim Audit 1 |
| UFW/unattended-upgrades | Grundschutz/automatische Sicherheitsupdates | kein verifiziertes externes Statussignal |

Beim Audit antwortete `/health` öffentlich mit HTTP 200 und Version 3.0.0. Die Anny Call History zeigte eine aktuelle erfolgreiche Zustellung, aber auch einen kumulierten Fehlerzähler von 1. Das ist eine Momentaufnahme.

## Nicht nachgewiesen

- externer Uptime-Check und Alarm auf `/health`
- DNS-/TLS-Ablaufalarm
- Disk-Space-/Inode-Alarm
- Alarm auf steigende Container-Restarts oder unhealthy
- wiederholte Allocator-/Webhook-Fehler als Pushalarm
- Alarm auf zukünftige `unassigned`-Buchungen
- Alarm auf Tischkollisionen
- automatischer Backup-Erfolgs-/Alters-/Integritätsalarm
- zentralisierte Logs mit definierter Aufbewahrung
- benannter Primär-/Sekundärempfänger und Eskalationszeit
- Provider-/Droplet-Monitoringagent im aktuellen Serverstand

**TODO – vor finaler Übergabe verifizieren:** DigitalOcean-Agent/Alerts, bestehende externe Checks, Cron-/systemd-Monitorjobs und sämtliche Alarmempfänger direkt in den Providerkonten und auf dem Server auditieren.

## Für Übergabereife empfohlen

### P0 – vor Übergabe

1. Externer HTTPS-Check auf `/health` mindestens jede Minute bis fünf Minuten.
2. Alarm an mindestens zwei von Philipp unabhängige Empfänger plus dokumentierte Eskalation.
3. täglicher Backupjob mit Alarm bei Ausfall, zu altem Backup, Hash-/Integritätsfehler oder fehlender Offsite-Kopie.
4. Kollision (`dashboard status=red`) sofort alarmieren.
5. zukünftige `unassigned`-Buchung und wiederholte retry-fähige Webhookfehler alarmieren.
6. DigitalOcean-/Domain-/Anny-Billing- und Ablaufalarme organisatorisch zustellen.

### P1 – sollte vor Übergabe

1. Diskalarm bei <20 % frei beziehungsweise Warnung und kritisch bei <10 %.
2. Container unhealthy oder RestartCount-Anstieg alarmieren.
3. DNS-/TLS-Prüfung mit Zertifikatswarnung spätestens 21/14 Tage vor Ablauf.
4. Anny-Webhook-Aktivstatus und Call-History-Fehlerserie überwachen.
5. monatlicher Testalarm und dokumentierte Bestätigung des Empfangs.

### P2 – Verbesserung

- zentrale, datensparsame Logaggregation
- trendfähige Metriken für Eventvolumen, Latenz und Reconciliation
- synthetischer, nichtproduktiver Integrationscheck, falls Anny eine sichere Testumgebung bietet

## Empfohlene Alarmmatrix

| Bedingung | Schweregrad | Reaktion |
| --- | --- | --- |
| `/health` zweimal nacheinander nicht 200 | kritisch | sofort Technical Owner; nach 5 min Business Owner |
| Dashboard Rot/Kollision | kritisch | sofort Betrieb + Technical Owner, betroffenen Slot absichern |
| zukünftige `unassigned`-Buchung | hoch | innerhalb 15 min prüfen; vor Termin eskalieren |
| retry-fähige Webhookfehler wiederholt | hoch | Anny/API/Token prüfen, Retryfenster beachten |
| Container unhealthy/RestartCount steigt | hoch | Logs/Exit/OOM prüfen, ggf. Rollback |
| Disk <20 % | Warnung | Ursache/Retention planen |
| Disk <10 % | kritisch | kontrolliert Kapazität schaffen/erweitern |
| Backup >26 h alt oder Integrität nicht `ok` | kritisch | Backupjob reparieren; kein Deployment |
| Offsite-Kopie fehlt | kritisch | Failure Domain wiederherstellen |
| TLS <21 Tage ohne erfolgreiche Erneuerung | Warnung | DNS/Caddy/ACME prüfen |
| Anny Token <30 Tage bis Ablauf | Warnung | Rotation terminieren |
| fünf konsekutive Webhookfehler drohen | kritisch | Ursache sofort beheben, Aktivstatus prüfen |

Schwellen sind Übergabevorschläge und müssen nach realem Betrieb organisatorisch bestätigt werden.

## Manuelle tägliche Kurzprüfung bis zur Automatisierung

```bash
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
ssh <ADMIN_USER>@138.68.87.128
cd /opt/anny_webhook
docker compose ps
docker inspect --format 'health={{if .State.Health}}{{.State.Health.Status}}{{end}} restarts={{.RestartCount}}' anny_webhook-allocator-1
df -h /
```

Zusätzlich Dashboard und Anny Call History öffnen. Diese Routine ist ein zeitlich begrenzter Ersatz, kein tragfähiges 24/7-Monitoring.

## Monitoring-Sicherheit und Datenschutz

- `/health` enthält keine Credentials und darf öffentlich überwacht werden.
- Dashboard und `/dashboard/data` bleiben authentifiziert; Monitoring-Credentials müssen getrennt und minimal sein. Aktuell existiert nur der gemeinsame Dashboard-Login.
- Keine vollständigen Webhook-Payloads, Authorization-Header, Query-Strings, Kundennamen oder E-Mail-Adressen in Alerts.
- Secretwerte nicht als Monitoringlabels oder URL-Parameter speichern. Der historische Webhook-Key in der URL ist besonders schützenswert.
- Alert- und Log-Retention organisatorisch festlegen.

## Abnahme des Monitorings

Vor Übergabe muss eine zweite Person ohne Philipps Hilfe:

1. Monitoringkonto öffnen,
2. alle Checks und Empfänger identifizieren,
3. einen Testalarm auslösen,
4. Empfang bei Primär und Backup bestätigen,
5. Ausfall-/Disk-/Backup-/Kollisions-Eskalation erklären,
6. Account-Recovery und Billing verifizieren.

Bis diese Abnahme dokumentiert ist, bleibt Monitoring ein Handover-Blocker.
