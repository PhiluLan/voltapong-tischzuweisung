# Rekonstruierter Ist-Zustand

Stand: 1. September 2026. Diese Datei trennt bewusst belegte Fakten von noch zu verifizierenden Annahmen.

## Gefundener Codebestand

Die Datei `app.py` entspricht bytegenau der zuletzt lokal auffindbaren, am 2. März 2026 gespeicherten VS-Code-Version. SHA-256:

```text
e0ae5a37a183e351595a3b6c0bee571dd31071bb543c05e276cdd9c07c603f75
```

Sie enthält Ressourcenfilter, Webhook-Authentifizierung, Verarbeitung von Erstellen/Aktualisieren/Löschen, Stornobereinigung, zusammenhängende und verteilte Tischwahl sowie SQLite-Migrationen.

Nicht verifiziert ist, ob auf dem Produktionsserver exakt dieselbe Datei läuft. Die frühere Ablage deutet auf `/opt/anny_webhook` und einen vorgeschalteten Caddy-Reverse-Proxy hin; ohne aktuellen Serverzugriff bleibt das eine Arbeitsannahme.

## Beobachteter Produktionszustand

Bei der Bestandsaufnahme war der öffentlich erreichbare Health-Endpunkt erfolgreich. Der Allocator meldete 763 lokale Einträge:

| Status | Anzahl |
| --- | ---: |
| Zugewiesen | 707 |
| Nicht zugewiesen | 56 |
| Aktiv oder zukünftig | 53 |

Für die konfigurierte Ressource `181227` wurden keine gleichzeitigen Doppelbelegungen desselben Tischlabels im geprüften Bestand gefunden.

Der Vergleich aktueller Anny-Daten mit lokalen Einträgen zeigte mindestens eine zugewiesene Buchung, deren gespeicherter Bedarf nicht mehr zum aktuellen `weight` passte, sowie zwei Abweichungen bei Zeitangaben. Das passt zum bekannten Verhalten des Schleifenschutzes bei `bookings.updated`: enthält die Buchung bereits den eigenen Marker, kann eine fachlich relevante Änderung übersprungen werden.

Alle 13 zum Prüfzeitpunkt zukünftigen `unassigned`-Einträge gehörten zum Service `83985`, der in einem später gefundenen internen Katalog als Gruppenvorlage beschrieben war. Vor einer Codeänderung muss fachlich entschieden werden, ob dieser Service überhaupt Tischzuweisung benötigt oder explizit ausgeschlossen werden soll.

Diese Zahlen sind eine Momentaufnahme und keine automatisierte, fortlaufende Kennzahl.

## Priorisierte Baustellen

### Kritisch vor dem nächsten Deployment

1. Produktionsdateien und Umgebungsvariablennamen sichern und mit diesem Stand vergleichen.
2. Den lokal gefundenen Anny-Token als kompromittiert behandeln, widerrufen und ersetzen.
3. Ein starkes `WEBHOOK_SECRET` setzen und die öffentliche Erreichbarkeit von `/allocations` schließen.
4. Vor Migration der Datenbank ein konsistentes Backup erstellen.

### Hohe fachliche Priorität

1. Eigene PATCH-Ereignisse gezielt erkennen, ohne echte Änderungen an Zeitraum, Ressource oder Bedarf zu ignorieren.
2. Anny-PATCH-Antworten auf `errors` prüfen und nur erfolgreiche Änderungen als gepatcht markieren.
3. `unassigned`-Buchungen erneut berechnen, wenn Storno, Löschung oder Terminänderung Kapazität freigibt.
4. Eine Reconciliation-Funktion bauen, die SQLite regelmäßig gegen Anny prüft und Abweichungen meldet oder kontrolliert repariert.
5. Gleichzeitige Webhooks serialisieren oder die Zuweisung transaktional absichern.

### Mittlere Priorität

1. Festlegen, ob Service `83985` ausgeschlossen, anders gewichtet oder separat behandelt wird.
2. Kunden- und interne Notizen nicht vollständig überschreiben, sondern einen klar abgegrenzten verwalteten Abschnitt pflegen.
3. Query-Parameter-Authentifizierung entfernen und Secret-Vergleich robust gestalten.
4. Strukturierte Logs, Metriken und Alarmierung für `unassigned`, API-Fehler und Bestandsabweichungen ergänzen.
5. Integrations- und Migrations-Tests ergänzen; die neuen Basistests decken zunächst nur deterministische Kernlogik ab.

## Abgrenzung

Der WhatsApp-Bot ist für diesen Arbeitsschritt ausdrücklich ausgeklammert. Seine Dateien, Zugangsdaten und Laufzeit gehören nicht in dieses Repository. Hinweise aus späteren internen Service-Katalogen wurden nur verwendet, soweit sie die fachliche Interpretation bestehender Tischzuweisungen erklären.
