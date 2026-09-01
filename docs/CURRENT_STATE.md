# Rekonstruierter Ist-Zustand

Stand: 1. September 2026. Diese Datei trennt bewusst belegte Fakten von noch zu verifizierenden Annahmen.

## Ausgangsbasis des Repositorys

Die Datei `app.py` entspricht bytegenau der zuletzt lokal auffindbaren, am 2. März 2026 gespeicherten VS-Code-Version. SHA-256:

```text
e0ae5a37a183e351595a3b6c0bee571dd31071bb543c05e276cdd9c07c603f75
```

Diese Datei war die unveränderte Baseline des ersten Git-Commits `7d57f67`. Sie enthält Ressourcenfilter, Webhook-Authentifizierung, Verarbeitung von Erstellen/Aktualisieren/Löschen, Stornobereinigung, zusammenhängende und verteilte Tischwahl sowie SQLite-Migrationen.

Das Repository entwickelt diese Baseline nun weiter. Neu implementiert, getestet und noch nicht produktiv ausgerollt sind:

- geschütztes Mitarbeiter-Dashboard unter `/dashboard`
- Schutz des vollständigen `/allocations`-Exports durch dieselbe Basic Auth
- Ampelprüfung auf offene Zuweisungen, ungültige Datensätze und Tischkollisionen
- bedarfsabhängige Bereinigung stornierter oder bei Anny gelöschter Kapazitätsblocker
- erneute Tischwahl direkt nach dieser Bereinigung
- Ausschluss der eigenen bestehenden Allocation bei einer Neuberechnung

Nicht verifiziert ist weiterhin, ob auf dem Produktionsserver exakt die ursprüngliche Baseline läuft. Vor einem Deployment muss `/opt/anny_webhook/app.py` bytegenau gesichert und verglichen werden.

## Beobachteter Produktionszustand

Die öffentliche Produktionsprüfung bestätigte am 1. September 2026:

- `webhook.voltabreau.ch` zeigt auf `138.68.87.128`.
- Ein gültiges Let's-Encrypt-Zertifikat und Caddy terminieren HTTPS.
- Uvicorn/FastAPI beantwortet `/health` erfolgreich.
- Das vollständige damalige OpenAPI-Dokument war identisch mit der Repository-Baseline.
- `POST /` ohne Webhook-Secret wurde korrekt mit HTTP 401 abgewiesen.

Der Allocator meldete 763 lokale Einträge:

| Status | Anzahl |
| --- | ---: |
| Zugewiesen | 707 |
| Nicht zugewiesen | 56 |
| Aktiv oder zukünftig | 53 |

Für die konfigurierte Ressource `181227` wurden keine gleichzeitigen Doppelbelegungen desselben Tischlabels im geprüften Bestand gefunden.

Der Vergleich aktueller Anny-Daten mit lokalen Einträgen zeigte mindestens eine zugewiesene Buchung, deren gespeicherter Bedarf nicht mehr zum aktuellen `weight` passte, sowie zwei Abweichungen bei Zeitangaben. Das passt zum bekannten Verhalten des Schleifenschutzes bei `bookings.updated`: enthält die Buchung bereits den eigenen Marker, kann eine fachlich relevante Änderung übersprungen werden.

Alle 13 zum Prüfzeitpunkt zukünftigen `unassigned`-Einträge gehörten zum Service `83985`, der in einem später gefundenen internen Katalog als Gruppenvorlage beschrieben war. Vor einer Codeänderung muss fachlich entschieden werden, ob dieser Service überhaupt Tischzuweisung benötigt oder explizit ausgeschlossen werden soll.

Diese Zahlen sind eine Momentaufnahme und keine automatisierte, fortlaufende Kennzahl. Die beiden lokalen SQLite-Dateien auf dem Mac waren leer und sind keine Produktionskopien.

## Priorisierte Baustellen

### Kritisch vor dem nächsten Deployment

1. Produktionsdateien und Umgebungsvariablennamen sichern und mit diesem Stand vergleichen.
2. Den lokal gefundenen Anny-Token als kompromittiert behandeln, widerrufen und ersetzen.
3. Ein starkes `WEBHOOK_SECRET`, `DASHBOARD_USERNAME` und `DASHBOARD_PASSWORD` setzen. Der neue Code schließt `/allocations`; auf der noch laufenden alten Produktionsversion bleibt der Endpunkt bis zum Deployment öffentlich.
4. Vor Migration der Datenbank ein konsistentes Backup erstellen.

### Hohe fachliche Priorität

1. Eigene PATCH-Ereignisse gezielt erkennen, ohne echte Änderungen an Zeitraum, Ressource oder Bedarf zu ignorieren.
2. Anny-PATCH-Antworten auf `errors` prüfen und nur erfolgreiche Änderungen als gepatcht markieren.
3. Bereits bestehende `unassigned`-Buchungen aktiv erneut berechnen, wenn Storno, Löschung oder Terminänderung Kapazität freigibt. Neue Buchungen werden durch die implementierte Kapazitäts-Reconciliation bereits selbstheilend behandelt.
4. Die gezielte Kapazitäts-Reconciliation später um einen kontrollierten vollständigen Bestandsabgleich erweitern.
5. Gleichzeitige Webhooks serialisieren oder die Zuweisung transaktional absichern.

### Mittlere Priorität

1. Festlegen, ob Service `83985` ausgeschlossen, anders gewichtet oder separat behandelt wird.
2. Kunden- und interne Notizen nicht vollständig überschreiben, sondern einen klar abgegrenzten verwalteten Abschnitt pflegen.
3. Query-Parameter-Authentifizierung entfernen und Secret-Vergleich robust gestalten.
4. Strukturierte Logs und externe Alarmierung für `unassigned`, API-Fehler und Bestandsabweichungen ergänzen. Das neue Dashboard macht diese Zustände bereits manuell sichtbar.
5. Echte Anny-Sandbox-Integrations- und Migrations-Tests ergänzen. Die lokale Suite deckt Kernlogik, Storno-Selbstheilung, Authentifizierung und Dashboard-Ampel ab.

## Abgrenzung

Der WhatsApp-Bot ist für diesen Arbeitsschritt ausdrücklich ausgeklammert. Seine Dateien, Zugangsdaten und Laufzeit gehören nicht in dieses Repository. Hinweise aus späteren internen Service-Katalogen wurden nur verwendet, soweit sie die fachliche Interpretation bestehender Tischzuweisungen erklären.
