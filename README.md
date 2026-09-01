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

Der aktuelle Algorithmus arbeitet so:

1. Nur konfigurierte Anny-Ressourcen werden berücksichtigt.
2. Der Buchungswert `weight` bestimmt die Anzahl benötigter Tische; fehlt oder passt er nicht, gilt `1`.
3. Überschneidende, bereits zugewiesene Buchungen derselben Ressource markieren Tische als belegt.
4. Der Dienst wählt zuerst eine zusammenhängende Tischgruppe, danach beliebige freie Tische.
5. Erscheint die Kapazität lokal voll, werden die blockierenden Buchungen nochmals bei Anny geprüft. Bestätigte Stornos und gelöschte Buchungen werden aus SQLite entfernt und die Tischwahl wird sofort wiederholt.
6. Reichen die freien Tische danach weiterhin nicht, wird die Buchung als `unassigned` gespeichert und in Anny entsprechend markiert.
7. Die Zuweisung wird in `customer_note`, `note` und `description` der Anny-Buchung geschrieben.

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
| `AUTO_MARKER` | Marker im Beschreibungstext | `TISCHE:` |
| `AUTO_PREFIX` | Präfix der internen Notiz | `Auto-Allocation:` |
| `WEBHOOK_SECRET` | Secret für Header `X-Webhook-Secret` | erforderlich für Produktion |
| `DASHBOARD_USERNAME` | Benutzername für Dashboard und `/allocations` | erforderlich |
| `DASHBOARD_PASSWORD` | langes, eigenständiges Dashboard-Passwort | erforderlich |
| `DASHBOARD_REFRESH_SECONDS` | Aktualisierungsintervall des Dashboards | `30`, mindestens `10` |
| `DEBUG` | Debug-Ausgaben | `0` |

Die historische Abwärtskompatibilität akzeptiert das Webhook-Secret zusätzlich als Query-Parameter `key`. Für neue Konfigurationen sollte ausschließlich der Header verwendet werden, weil Query-Strings häufig in Logs landen.

## Betrieb und Weiterentwicklung

- [docs/OPERATIONS.md](docs/OPERATIONS.md): Bestandsaufnahme, Deployment, Backup und Rollback
- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md): belegter Produktionsstand und priorisierte Baustellen
- [SECURITY.md](SECURITY.md): Secret- und Datenschutzregeln

Das Repository wurde aus der zuletzt lokal gefundenen Version vom 2. März 2026 aufgebaut und wird seitdem als Entwicklungsbasis weitergeführt. Die Produktionsinstanz zeigt dieselben ursprünglichen Routen und ein identisches ursprüngliches OpenAPI-Dokument; ein bytegenauer Dateivergleich mit `/opt/anny_webhook/app.py` ist ohne Root-Zugang weiterhin offen. Dashboard und Kapazitäts-Selbstheilung sind noch nicht produktiv ausgerollt.

## Nicht im Projektumfang

Der separat gefundene WhatsApp-Bot ist bewusst nicht Bestandteil dieses Repositorys. Er wird weder gebaut noch deployt und hat keinen Einfluss auf die hier dokumentierte Tischzuweisung.
