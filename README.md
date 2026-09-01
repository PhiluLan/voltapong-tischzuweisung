# Volta Pong Tischzuweisung

Kleiner FastAPI-Dienst, der eingehende Anny-Buchungsereignisse verarbeitet und die acht Volta-Pong-Tische konfliktfrei zuweist. Anny bleibt das führende System für Buchungen; SQLite speichert ausschließlich den vom Dienst berechneten Belegungszustand.

## Ablauf

```text
Anny-Webhook
    |
    v
POST /  -- Secret prüfen --> Buchung über Anny API laden
    |                              |
    |                              v
    |                   Zeitraum, Ressource und Bedarf
    |                              |
    v                              v
SQLite-Belegungen <------ freie Tische berechnen
                                   |
                     zusammenhängend -> beliebig frei
                                   |
                                   v
                         Anny-Buchung ergänzen
```

Der aktuelle Entwicklungsstand arbeitet so:

1. Die Anny-`event_id` verhindert doppelte Verarbeitung wiederholter Zustellungen.
2. Nur konfigurierte Anny-Ressourcen werden berücksichtigt.
3. Der Buchungswert `weight` bestimmt die Anzahl benötigter Tische; fehlt oder passt er nicht, gilt `1`.
4. Überschneidende, bereits zugewiesene Buchungen derselben Ressource markieren Tische als belegt.
5. Der Dienst wählt zuerst eine zusammenhängende Tischgruppe, danach beliebige freie Tische.
6. Erscheint die Kapazität lokal voll, werden die Blocker nochmals bei Anny geprüft. Bestätigte Stornos und gelöschte Buchungen werden entfernt und die Tischwahl wird wiederholt.
7. Bei `bookings.deleted`, Storno oder einer kapazitätsrelevanten Änderung wird der alte Zeitraum freigegeben. Passende `unassigned`-Buchungen werden anschließend geordnet erneut versucht.
8. Echte Änderungen an Zeitraum, Ressource oder `weight` werden auch dann verarbeitet, wenn die Buchung bereits die eigene Tischmarkierung enthält.
9. Temporäre Anny-GET- oder PATCH-Fehler liefern HTTP 503. Anny kann dasselbe Ereignis anschließend sicher erneut zustellen.
10. Die Zuweisung wird in `customer_note`, `note` und einem verwalteten Abschnitt der `description` geschrieben.

Eine detaillierte Beschreibung steht in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Der rekonstruierte Ist-Zustand und alle bekannten Risiken stehen in [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md).

## Schnellstart mit Docker

Voraussetzungen: Docker mit Compose und ein neuer Anny-API-Token.

```bash
cp .env.example .env
# .env sicher ausfüllen
docker compose up --build -d
curl http://127.0.0.1:8099/health
```

Persistente Laufzeitdaten landen unter `./data/` und werden nicht versioniert.

Das geschützte Mitarbeiter-Dashboard ist danach unter `http://127.0.0.1:8099/dashboard` erreichbar. Der Browser fragt nach `DASHBOARD_USERNAME` und `DASHBOARD_PASSWORD` aus der lokalen `.env`.

## Anny-Webhook konfigurieren

Für die Tischzuweisung werden genau diese offiziellen Buchungsereignisse benötigt:

- `bookings.created`: neue Buchung zuweisen
- `bookings.updated`: echte Änderungen oder einen Storno-Status verarbeiten
- `bookings.deleted`: gelöschte **oder stornierte** Buchung entfernen und Kapazität nachverteilen

In Anny sollte der Webhook auf die produktive Ping-Pong-Ressource `181227` beschränkt werden. Ereignisse wie `bookings.started`, `bookings.ended`, `bookings.checked-in` und `bookings.checked-out` werden für die Tischwahl nicht benötigt. Die offizielle Payload enthält `event_id`; fehlgeschlagene Zustellungen werden von Anny erneut versucht.

## Produktion

`docker-compose.production.yml` bildet die verifizierte Live-Topologie mit Caddy, internem Allocator-Port, Healthcheck und begrenzten Docker-Logs ab. Es darf erst nach Backup, Secret-Rotation und kontrolliertem Test verwendet werden:

```bash
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml up -d
```

Der Stand `c261d029d8929582aa8d0628267c79003e0093be` ist seit dem 1. September 2026 produktiv unter `https://webhook.voltabreau.ch` aktiv. Das geschützte Dashboard ist unter `https://webhook.voltabreau.ch/dashboard` erreichbar. Ein Git-Push löst derzeit noch kein automatisches Deployment aus.

## Lokale Entwicklung

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# .env mit lokalen Werten ausfüllen
pytest
python -m uvicorn app:app --host 127.0.0.1 --port 8099 --reload
```

Die Tests verwenden ausschließlich Dummy-Zugangsdaten und eine temporäre SQLite-Datenbank. Sie greifen nicht auf Anny zu.

## Endpunkte

| Methode | Pfad | Aufgabe |
| --- | --- | --- |
| `GET` | `/health` | Prozess- und Erreichbarkeitsprüfung |
| `POST` | `/` | Anny-Webhook für `bookings.created`, `bookings.updated` und `bookings.deleted` |
| `GET` | `/dashboard` | Geschützter, laienverständlicher Systemstatus |
| `GET` | `/dashboard/data` | Aggregierte Statusdaten ohne Kundennamen oder Kontaktdaten |
| `GET` | `/allocations` | Geschützter vollständiger lokaler Zuweisungsbestand |

Dashboard, Statusdaten und `/allocations` sind über HTTP Basic Auth geschützt und arbeiten ohne konfigurierte Zugangsdaten absichtlich nicht. `/health` bleibt für Monitoring öffentlich.

## Konfiguration

| Variable | Bedeutung | Beispiel/Standard |
| --- | --- | --- |
| `ANNY_BASE` | Basis-URL der Anny API | `https://b.anny.co/api/v1` |
| `ANNY_TOKEN` | Bearer-Token für Anny | erforderlich |
| `ANNY_TZ` | dokumentierte Betriebszeitzone | `Europe/Zurich` |
| `ALLOCATOR_DB` | SQLite-Datei | lokal `./data/allocator.db`, im Container `/data/allocator.db` |
| `ALLOCATE_RESOURCE_IDS` | erlaubte Ressourcen, kommasepariert | Produktion: `181227` |
| `TABLE_LABELS` | geordnete Tischliste | `Tisch 1` bis `Tisch 8` |
| `HANDLE_UPDATED` | Update-Ereignisse verarbeiten | `1` |
| `REDISTRIBUTION_LIMIT` | Maximal pro freiem Zeitfenster erneut geprüfte offene Buchungen | `20` |
| `WEBHOOK_EVENT_RETENTION_DAYS` | Aufbewahrung verarbeiteter `event_id`-Einträge | `90` |
| `AUTO_MARKER` | Marker im Beschreibungstext | `TISCHE:` |
| `AUTO_PREFIX` | Präfix der internen Notiz | `Auto-Allocation:` |
| `WEBHOOK_SECRET` | Secret für Header `X-Webhook-Secret` | erforderlich für Produktion |
| `DASHBOARD_USERNAME` | Benutzername für Dashboard und `/allocations` | erforderlich |
| `DASHBOARD_PASSWORD` | langes, eigenständiges Dashboard-Passwort | erforderlich |
| `DASHBOARD_REFRESH_SECONDS` | Aktualisierungsintervall des Dashboards | `30`, mindestens `10` |
| `DEBUG` | Debug-Ausgaben | `0` |

Die historische Abwärtskompatibilität akzeptiert das Webhook-Secret zusätzlich als Query-Parameter `key`. Für neue Konfigurationen sollte ausschließlich der Header verwendet werden, weil Query-Strings häufig in Logs landen.

## Betrieb und Weiterentwicklung

- [docs/handover/README.md](docs/handover/README.md): vollständiges Technical Handover Package für Ownership, Betrieb, Recovery und Offboarding
- [docs/HANDBUCH.md](docs/HANDBUCH.md): laienverständlicher Gesamtüberblick und Alltagshilfe
- [docs/OPERATIONS.md](docs/OPERATIONS.md): Bestandsaufnahme, Deployment, Backup und Rollback
- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md): belegter Produktionsstand und priorisierte Baustellen
- [docs/ZUKUNFT.md](docs/ZUKUNFT.md): Bewertung von Droplet, Domain, SSH und Managed-Alternativen
- [SECURITY.md](SECURITY.md): Secret- und Datenschutzregeln

Das Repository wurde aus der zuletzt lokal gefundenen Version vom 2. März 2026 aufgebaut. Nach Root-Audit, konsistenten Backups, Secret-Rotation, isolierten Smoke-Tests und einem kontrollierten Live-End-to-End-Test wurde die neue Version am 1. September 2026 produktiv ausgerollt. Storno, Freigabe und direkte Wiederbelegung desselben Tischs wurden mit echten Anny-Buchungen erfolgreich bestätigt.

## Nicht im Projektumfang

Der separat gefundene WhatsApp-Bot ist bewusst nicht Bestandteil dieses Repositorys. Er wird weder gebaut noch deployt und hat keinen Einfluss auf die hier dokumentierte Tischzuweisung.
