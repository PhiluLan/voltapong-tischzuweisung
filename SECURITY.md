# Sicherheit

## Geheimnisse und personenbezogene Daten

Folgende Inhalte dürfen nie in Git eingecheckt werden:

- `.env` und echte Werte für `ANNY_TOKEN`, `WEBHOOK_SECRET` oder das Dashboard-Passwort
- `allocator.db`, SQLite-Nebendateien und Datenbank-Backups
- Server-Backups, Logs oder Exporte mit Buchungs- und Kundendaten

Das Repository ignoriert diese Dateien. Die Beispielkonfiguration enthält nur Platzhalter.

Bei der lokalen Bestandsaufnahme wurde ein zuvor kopierter echter Anny-Token in einer Beispieldatei gefunden. Er ist damit als kompromittiert zu behandeln und muss vor dem nächsten Deployment in Anny widerrufen und ersetzt werden. Das gilt auch dann, wenn die Datei nie öffentlich hochgeladen wurde.

## Offene Sicherheitsaufgaben

1. Anny-Token und Webhook-Secret rotieren.
2. Den neuen Basic-Auth-Schutz für `/dashboard`, `/dashboard/data` und `/allocations` mit eigenständigen, langen Zugangsdaten produktiv konfigurieren. Bis zum Deployment bleibt `/allocations` auf der alten Produktionsversion öffentlich.
3. Das Webhook-Secret ausschließlich im Header `X-Webhook-Secret` übertragen; die Query-Parameter-Kompatibilität anschließend entfernen.
4. Service und Reverse Proxy mit minimalen Rechten betreiben und Datenbank-Backups verschlüsseln.
5. Keine vollständigen Webhook-Payloads oder API-Header protokollieren.

## Dashboard-Zugriff

Der neue Code arbeitet fail-closed: Fehlen `DASHBOARD_USERNAME` oder `DASHBOARD_PASSWORD`, liefern Dashboard und `/allocations` HTTP 503 statt Daten öffentlich auszugeben. Die Zugangsdaten dürfen nicht mit dem Webhook-Secret oder dem Anny-Token identisch sein. Basic Auth ist ausschließlich über die vorhandene HTTPS-Domain zulässig.

## Meldung eines Problems

Sicherheitsprobleme bitte nicht als öffentliches GitHub-Issue mit Secrets, Buchungsnummern oder Kundendaten melden. Zugangsdaten sofort widerrufen und die betroffenen Logs beziehungsweise Zeiträume getrennt dokumentieren.
