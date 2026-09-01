# Rekonstruierter Ist-Zustand

Stand: 1. September 2026. Diese Datei trennt bewusst belegte Fakten von noch zu verifizierenden Annahmen.

## Ausgangsbasis des Repositorys

Die Datei `app.py` entspricht bytegenau der zuletzt lokal auffindbaren, am 2. März 2026 gespeicherten VS-Code-Version. SHA-256:

```text
e0ae5a37a183e351595a3b6c0bee571dd31071bb543c05e276cdd9c07c603f75
```

Diese Datei war die unveränderte Baseline des ersten Git-Commits `7d57f67`. Der Root-Audit am 1. September 2026 bestätigte denselben SHA-256 sowohl für `/opt/anny_webhook/app.py` als auch für `/app/app.py` im laufenden Container.

Das Repository entwickelt diese Baseline nun weiter. Neu implementiert, getestet und noch nicht produktiv ausgerollt sind:

- geschütztes Mitarbeiter-Dashboard unter `/dashboard`
- Schutz des vollständigen `/allocations`-Exports durch dieselbe Basic Auth
- Ampelprüfung auf offene Zuweisungen, ungültige Datensätze und Tischkollisionen
- bedarfsabhängige Bereinigung stornierter oder bei Anny gelöschter Kapazitätsblocker
- erneute Tischwahl direkt nach dieser Bereinigung
- Ausschluss der eigenen bestehenden Allocation bei einer Neuberechnung
- idempotente Verarbeitung der offiziellen Anny-`event_id`
- echte Neuberechnung bei Änderungen an Zeitraum, Ressource oder Bedarf
- automatische Nachverteilung älterer `unassigned`-Buchungen nach frei gewordener Kapazität
- HTTP-503-Retry bei temporären Anny-GET-/PATCH-Fehlern
- Serialisierung paralleler Zuweisungen im einzelnen Uvicorn-Prozess
- separate Produktions-Compose-Datei mit Caddy, Healthcheck und Logbegrenzung

Diese Erweiterungen sind lokal getestet, aber noch nicht produktiv ausgerollt. Der laufende Server wurde während des Audits nicht verändert.

## Beobachteter Produktionszustand

Die öffentliche Produktionsprüfung bestätigte am 1. September 2026:

- `webhook.voltabreau.ch` zeigt auf `138.68.87.128`.
- Ein gültiges Let's-Encrypt-Zertifikat und Caddy terminieren HTTPS.
- Uvicorn/FastAPI beantwortet `/health` erfolgreich.
- Das vollständige damalige OpenAPI-Dokument war identisch mit der Repository-Baseline.
- `POST /` ohne Webhook-Secret wurde korrekt mit HTTP 401 abgewiesen.

Nach einer während des Audits neu eingegangenen Buchung meldete der Allocator 766 lokale Einträge:

| Status | Anzahl |
| --- | ---: |
| Zugewiesen | 710 |
| Nicht zugewiesen | 56 |
| Aktiv oder zukünftig | 56 |

Für die konfigurierte Ressource `181227` wurden keine gleichzeitigen Doppelbelegungen desselben Tischlabels im geprüften Bestand gefunden.

Der Live-Abgleich zeigte sieben Abweichungen: fünf fehlende Beschreibungsmarker und zwei fachlich veraltete Datensätze. Bei `BB457317562` hält SQLite zwei Tische bis 20:00 UTC, während Anny drei Tische bis 18:00 UTC verlangt. Bei `BB868103531` endet der lokale Datensatz eine Stunde früher als die Anny-Buchung. Das bestätigt den Fehler des alten `bookings.updated`-Schleifenschutzes.

Alle 13 aktuellen oder zukünftigen `unassigned`-Einträge existierten in Anny weiterhin mit Status `accepted` und gehörten zum Service `83985`. Die Live-API identifizierte ihn eindeutig als „Gruppen Volta Bräu 4 Tische“; er muss daher regulär vier Tische erhalten. Acht dieser 13 Fälle wären nach dem gespeicherten Belegungsbild bereits wieder zuweisbar gewesen, wurden von der alten Version aber nie erneut versucht. Die neue Nachverteilung schließt genau diese Lücke.

Alle 42 zum Zeitpunkt des gezielten Statusabgleichs wirksamen `assigned`-Datensätze gehörten zu vorhandenen, nicht stornierten Anny-Buchungen. Es lag damit während des Audits kein aktuell bestätigter Storno-Blocker vor.

Diese Zahlen sind eine Momentaufnahme und keine automatisierte, fortlaufende Kennzahl. Die beiden lokalen SQLite-Dateien auf dem Mac waren leer und sind keine Produktionskopien.

## Priorisierte Baustellen

### Kritisch vor dem nächsten Deployment

1. Produktionsdateien und Umgebungsvariablennamen sind verglichen; vor dem Deployment trotzdem ein versioniertes Deployment-Paket und ein separates konsistentes Datenbank-Backup erstellen.
2. Den lokal gefundenen Anny-Token als kompromittiert behandeln, widerrufen und ersetzen.
3. Ein starkes `WEBHOOK_SECRET`, `DASHBOARD_USERNAME` und `DASHBOARD_PASSWORD` setzen. Der neue Code schließt `/allocations`; auf der noch laufenden alten Produktionsversion bleibt der Endpunkt bis zum Deployment öffentlich.
4. Vor Migration der Datenbank ein konsistentes Backup erstellen.

### Vor dem kontrollierten Rollout verifizieren

1. Die implementierten Update-, PATCH-, Nachverteilungs- und Parallelitätstests in einer isolierten Kopie der Produktionsdatenbank ausführen.
2. In Anny genau `bookings.created`, `bookings.updated` und `bookings.deleted` aktivieren; `deleted` umfasst laut offizieller Dokumentation auch Storno. Den Ressourcenfilter auf `181227` setzen.
3. Einen kontrollierten End-to-End-Test mit Testbuchung, echter Änderung, Vollbelegung, Storno und Nachverteilung durchführen.
4. Sicherstellen, dass Produktion weiterhin genau einen Uvicorn-Worker und einen Allocator-Container verwendet.
5. Die gezielte Event-Reconciliation später um einen kontrollierten vollständigen Bestandsabgleich erweitern.

### Mittlere Priorität

1. Kunden- und interne Notizen später ebenfalls als klar abgegrenzte verwaltete Abschnitte behandeln; die `description` tut dies bereits.
2. Query-Parameter-Authentifizierung entfernen, sobald die native Anny-Signatur technisch eindeutig dokumentiert und getestet ist.
3. Externe Alarmierung für `unassigned`, API-Fehler und Bestandsabweichungen ergänzen. Das Dashboard macht diese Zustände bereits manuell sichtbar.
4. Echte Anny-Sandbox-Integrations- und Migrations-Tests ergänzen. Die lokale Suite verwendet absichtlich keine echten Tokens.

## Abgrenzung

Der WhatsApp-Bot ist für diesen Arbeitsschritt ausdrücklich ausgeklammert. Seine Dateien, Zugangsdaten und Laufzeit gehören nicht in dieses Repository. Hinweise aus späteren internen Service-Katalogen wurden nur verwendet, soweit sie die fachliche Interpretation bestehender Tischzuweisungen erklären.
