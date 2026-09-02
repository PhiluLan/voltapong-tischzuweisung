# Aktueller Produktionsstand

Stand: 2. September 2026, nach Live-Rollout von Version 3.1.0.

## Verbindlicher Stand

- GitHub-Branch: `main`
- produktiver Commit: `6937aa89b9afb2c58409eb591fd4c952a70684ef`
- öffentliche Adresse: `https://webhook.voltabreau.ch`
- Dashboard: `https://webhook.voltabreau.ch/dashboard`
- Server: DigitalOcean-Droplet `138.68.87.128`, Ubuntu 24.04.3 LTS
- Anwendungspfad: `/opt/anny_webhook`
- Datenbank: `/opt/anny_webhook/data/allocator.db`
- Anny-Ressource: `181227` („Ping Pong Tisch“)
- produktive Anwendungsversion: `3.1.0`

`app.py`, Produktions-Compose-Datei und Caddyfile auf dem Server stimmen mit den geprüften Repository-Dateien überein. Das laufende Allocator-Image trägt den Git-Commit als OCI-Revision.

## Laufzeit

Zwei Docker-Container sind aktiv:

| Container | Aufgabe | Zustand |
| --- | --- | --- |
| `anny_webhook-allocator-1` | Webhook, Anny-API, Tischlogik, Dashboard, SQLite | `healthy`, read-only, Restart `unless-stopped` |
| `anny_webhook-caddy-1` | Ports 80/443, HTTPS, Reverse Proxy | aktiv |

Der Allocator-Port 8099 ist nur im Docker-Netz sichtbar. Öffentlich geöffnet sind SSH 22 sowie HTTP/HTTPS 80/443. UFW ist aktiv; automatische Ubuntu-Sicherheitsupdates sind aktiviert.

Der Server besitzt 1 CPU, rund 1 GB RAM und eine 24-GB-Systemplatte. Diese Größe ist für den heutigen einzelnen Allocator ausreichend.

## Zugangsdaten und Schutz

- Der aktive Anny-Token besitzt nur `b.bookings:read` und `b.bookings:update`.
- Der alte, überberechtigte Token `annyAPI` ist auf ausdrücklichen Wunsch noch nicht widerrufen, wird vom Server aber nicht mehr verwendet.
- Das Webhook-Secret wurde rotiert und stimmt zwischen Anny und Server überein.
- Uvicorn-Access-Logs sind deaktiviert, weil Anny das historische Secret noch im Query-Parameter sendet.
- Dashboard, `/dashboard/data` und `/allocations` sind per HTTP Basic Auth geschützt.
- Der Dashboard-Benutzername ist `planger@voltabraeu.ch`; das Passwort wird ausschließlich außerhalb von Git gespeichert.
- Die produktive `.env` besitzt Dateimodus `0600`.

Der Live-Server erlaubt momentan weiterhin `root`-Login und Passwortauthentifizierung per SSH. Das ist der wichtigste noch offene technische Härtungspunkt.

## Backups und Rollback

Vor dem Rollout wurden erstellt:

- `/opt/anny_webhook/backups/20260901T194300Z-pre-v3/`: alte Anwendung, Konfiguration, konsistentes SQLite-Backup und Rollback-Image
- `/opt/anny_webhook/backups/20260901T195900Z-postdeploy-pre-e2e.db`: konsistente Datenbank direkt vor dem End-to-End-Test
- `/opt/anny_webhook/backups/20260901T203752Z-pre-dashboard-credentials/.env`: Konfiguration vor Änderung des Dashboard-Logins
- `/opt/anny_webhook/backups/20260902T183231Z-pre-v3.1.0-allocator.db`: konsistentes SQLite-Backup unmittelbar vor Version 3.1.0
- `/opt/anny_webhook/backups/20260902T183430Z-predeploy-v3.1.0/`: vorherige Produktionsdateien für den Rollback
- Docker-Rollback-Tag `anny_webhook-allocator:rollback-20260902T183430Z`

Die geprüften SQLite-Backups meldeten `PRAGMA integrity_check = ok`. Lokale Backups auf demselben Droplet ersetzen kein Offsite- oder DigitalOcean-Droplet-Backup.

## Nachgewiesene Tests

### Automatisierte Suite

- 39 Tests erfolgreich
- Python-Kompilierung erfolgreich
- Compose-Konfiguration gültig
- isolierter Smoke-Test auf einer Kopie der Produktionsdatenbank erfolgreich
- Dashboard mit Auth HTTP 200, ohne Auth HTTP 401

### Sicherheits-Hotfix

Ein erster rotierter Webhook-Key erschien wegen des Query-Parameters im Uvicorn-Access-Log. Daraufhin wurde:

1. der Access-Log deaktiviert,
2. das Secret erneut rotiert,
3. das Image neu gebaut und der Container ersetzt,
4. geprüft, dass weder Query-Key noch Secret im neuen Container-Log vorkommen.

### Kontrollierter Vollbelegungs-/Storno-Test

Ein isoliert vorbereiteter Test belegte alle acht Tische, hielt eine echte Buchung als wartend und simulierte einen offiziellen Storno-Webhook. Ergebnis:

- Storno gab Kapazität frei,
- wartende Buchung wurde automatisch zugewiesen,
- Anny-Notizen wurden aktualisiert,
- keine technischen Testblocker blieben zurück,
- keine Kollision und kein retry-fähiger Fehler entstand.

### Echter Gästetest

Für den 27. September 2026, 09:00–10:00 Uhr:

1. `BB783001256` belegte bei Vollbelegung Tisch 8.
2. Die Buchung wurde in Anny storniert.
3. Anny lieferte den Storno tatsächlich als `bookings.updated` mit Status `canceled`.
4. Der Allocator entfernte die lokale Zeile mit Ergebnis `BOOKING_CANCELED_DB_CLEANED`; Tisch 8 war frei.
5. Die unmittelbar danach erstellte Buchung `BB855734593` erhielt automatisch Tisch 8.
6. `customer_note`, `note` und `description` waren in Anny synchron; die Bestätigungsmail enthielt „Deine Tische: Tisch 8“.
7. Der Zeitraum war anschließend wieder kollisionsfrei 8/8 belegt.

Damit ist der ursprüngliche Fehler „Storno in Anny, aber Tisch bleibt lokal blockiert“ praktisch im Live-System behoben.

### Zusätzliche Tischressourcen

Version 3.1.0 erkennt Anny-Hauptbuchungen und deren `sub_bookings`. Eine Hauptbuchung mit zwei zusätzlich gewählten Tischressourcen wird als Familie mit insgesamt drei Tischzuweisungen verarbeitet. Die Hauptbuchung erhält zuerst die vollständige Kundenangabe, beispielsweise `Deine Tische: Tisch 1, Tisch 2, Tisch 3`; danach werden die technischen Unterbuchungen einzeln beschriftet. Storno oder Löschung einer Unterbuchung aktualisiert die Hauptbuchung und gibt deren Tisch wieder frei.

Der produktiv gebaute Container bestand einen isolierten Smoke-Test mit Hauptbuchung plus zwei Unterbuchungen. Dabei wurden Produktions-Image und Compose-Umgebung verwendet, aber eine separate temporäre SQLite-Datei und abgefangene Anny-PATCH-Aufrufe. Ein echter neuer Gastbuchungs-/Mailtest für Version 3.1.0 ist noch ausstehend.

## Datenbankzustand nach Rollout

Der Abschlussaudit meldete:

| Prüfung | Ergebnis |
| --- | ---: |
| SQLite-Integrität | `ok` |
| Allocations gesamt | 773 |
| Zugewiesen | 767 |
| Nicht zugewiesen | 6 |
| Tischkollisionen | 0 |
| retry-fähige Webhook-Fehler | 0 |

Die Zahlen sind eine Momentaufnahme direkt nach dem Rollout. Zwei der sechs `unassigned`-Einträge lagen zu diesem Zeitpunkt noch in der Zukunft; deshalb war das Dashboard gelb. Es bestanden keine Tischkollisionen und keine retry-fähigen Webhook-Fehler der letzten 24 Stunden.

## Bekannter fachlicher Fehler: Anny-Kapazität gegen Tischbedarf

Am 7. September 2026 zeigte Anny für 19:00–20:00 Uhr acht Buchungen und ließ keine weitere Gastbuchung zu. Der Allocator hatte gleichzeitig nur sechs konkrete Tische zugewiesen; eine Buchung verlangte vier Tische, fand aber nicht genügend Gesamtkapazität.

Ursache ist kein verbliebener E2E-Blocker. Anny zählt in dieser Konstellation Buchungs-/Kapazitätseinheiten, während der Allocator das Feld `weight` als Anzahl physischer Tische interpretiert. Services mit einem und mehreren benötigten Tischen können deshalb fachlich auseinanderlaufen.

Dieser Punkt muss separat gelöst werden, beispielsweise durch eine konsistente Kapazitätsmodellierung in Anny oder echte einzelne Tischressourcen. Bis dahin bedeutet „8/8 in Anny“ nicht in jedem gemischten Zeitraum automatisch „alle acht physischen Tischlabels sind erfolgreich zugewiesen“.

## Priorisierte nächste Schritte

1. Nach Abschluss der Anwenderprüfung den alten Anny-Token `annyAPI` widerrufen.
2. Automatische DigitalOcean- und verschlüsselte Offsite-Backups einrichten.
3. Persönlichen SSH-Key und eingeschränkten Wartungsbenutzer anlegen; Root- und Passwort-Login deaktivieren.
4. Den Anny-/Tisch-Kapazitätsunterschied fachlich korrigieren.
5. Automatisierte Tests und Deployment vom GitHub-Commit bis zum unveränderlichen Server-Image aufbauen.
6. Persönliche Dashboard-Anmeldung oder vorgeschalteten Identity-Provider statt gemeinsamem Basic-Auth-Passwort einführen.
7. Periodischen vollständigen Abgleich zwischen Anny und SQLite ergänzen.

## Abgrenzung

Der separat gefundene WhatsApp-Bot gehört weiterhin nicht zu diesem Repository und hat keinen Einfluss auf die Tischzuweisung.
