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
5. Reichen die freien Tische nicht, wird die Buchung als `unassigned` gespeichert und in Anny entsprechend markiert.
6. Die Zuweisung wird in `customer_note`, `note` und `description` der Anny-Buchung geschrieben.

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
| `GET` | `/allocations` | Gesamten lokalen Zuweisungsbestand ausgeben |

`/allocations` ist im aktuellen Code nicht geschützt und enthält operative Buchungsdaten. Dieser Endpunkt darf erst nach einer Absicherung öffentlich erreichbar sein.

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
| `DEBUG` | Debug-Ausgaben | `0` |

Die historische Abwärtskompatibilität akzeptiert das Webhook-Secret zusätzlich als Query-Parameter `key`. Für neue Konfigurationen sollte ausschließlich der Header verwendet werden, weil Query-Strings häufig in Logs landen.

## Betrieb und Weiterentwicklung

- [docs/OPERATIONS.md](docs/OPERATIONS.md): Bestandsaufnahme, Deployment, Backup und Rollback
- [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md): belegter Produktionsstand und priorisierte Baustellen
- [SECURITY.md](SECURITY.md): Secret- und Datenschutzregeln

Der Anwendungscode in diesem ersten Repository-Stand ist eine unveränderte Sicherung der zuletzt lokal gefundenen Version vom 2. März 2026. Ob exakt diese Datei auf dem Produktionsserver läuft, konnte ohne Serverzugriff nicht verifiziert werden. Vor dem nächsten Deployment ist deshalb ein Dateivergleich mit `/opt/anny_webhook/app.py` zwingend.

## Nicht im Projektumfang

Der separat gefundene WhatsApp-Bot ist bewusst nicht Bestandteil dieses Repositorys. Er wird weder gebaut noch deployt und hat keinen Einfluss auf die hier dokumentierte Tischzuweisung.
