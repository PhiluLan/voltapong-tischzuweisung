# Betrieb, Deployment und Wiederherstellung

## Einmalige Bestandsaufnahme des Produktionsservers

Vor dem ersten Deployment aus Git müssen die tatsächlich laufenden Dateien gesichert und verglichen werden. Erwarteter historischer Pfad: `/opt/anny_webhook`.

Zu sichern beziehungsweise zu erfassen sind mindestens:

- `app.py` mit SHA-256-Prüfsumme
- `Dockerfile` und Compose-Datei
- Reverse-Proxy-Konfiguration, historisch vermutlich Caddy
- Namen der gesetzten Umgebungsvariablen, niemals deren Werte in Tickets oder Git
- Containername, Image, Ports, Volumes und Restart-Policy
- konsistentes Backup von `allocator.db`

Der Root-Audit vom 1. September 2026 hat diese Punkte bis auf ein konsistentes Datenbank-Backup abgeschlossen. Live-Code und Container entsprechen der Baseline `7d57f67`; `/opt/anny_webhook/docker-compose.yml` und `Caddyfile` wurden mit `docker-compose.production.yml` beziehungsweise `Caddyfile` im Repository abgebildet.

## Lokal prüfen

```bash
cp .env.example .env
# Dummy- oder Entwicklungswerte setzen
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
docker compose config --quiet
docker compose -f docker-compose.production.yml config --quiet
docker compose build
```

Für einen lokalen Lauf mit echten Anny-Zugangsdaten muss der Webhook so geschützt sein, dass keine fremden Buchungs-IDs verarbeitet werden können.

Dashboard lokal prüfen:

```bash
curl --user "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" http://127.0.0.1:8099/dashboard/data
```

Das Passwort nicht direkt in gemeinsam sichtbare Shell-Historien schreiben. Der Befehl dient nur als Form; im normalen Betrieb wird `/dashboard` im Browser geöffnet und der Browser fragt nach den Zugangsdaten.

## Datenbank sichern

Bei laufendem Container ist die SQLite-Backup-API sicherer als eine rohe Kopie der geöffneten Datei. Beispiel, falls Service und Volume wie in diesem Repository heißen:

```bash
docker compose exec allocator python -c "import sqlite3; src=sqlite3.connect('/data/allocator.db'); dst=sqlite3.connect('/data/allocator.backup.db'); src.backup(dst); dst.close(); src.close()"
```

Die erzeugte Datei anschließend außerhalb des öffentlich erreichbaren Verzeichnisses ablegen, Zugriffsrechte beschränken und nicht in Git übernehmen. Vor jedem Restore den Container stoppen und sowohl Original als auch Backup mit `PRAGMA integrity_check` prüfen.

## Deployment-Zielbild

Nach abgeschlossenem Vergleich:

1. Repository in ein neues Release-Verzeichnis klonen oder per CI ein unveränderliches Image bauen.
2. Produktions-`.env` aus dem Secret Store beziehungsweise direkt auf dem Host bereitstellen.
   Zwingend neu setzen: `ANNY_TOKEN`, `WEBHOOK_SECRET`, `DASHBOARD_USERNAME` und `DASHBOARD_PASSWORD`.
3. Bestehende Datenbank als Volume einbinden.
4. `docker-compose.production.yml` verwenden; die lokale `docker-compose.yml` ist nicht die Produktionsdefinition.
5. Container bauen und starten.
6. Intern `/health` prüfen, dann einen kontrollierten Test-Webhook verwenden.
7. `https://webhook.voltabreau.ch/dashboard` im Browser öffnen und Grün-/Gelb-/Rot-Anzeige sowie Basic Auth prüfen.
8. `/allocations` ohne Zugangsdaten muss HTTP 401 liefern; mit Dashboard-Zugang darf der Endpunkt funktionieren.
9. Logs, Dashboard und Anny-Buchung des kontrollierten Tests prüfen.
10. Einen End-to-End-Test durchführen: Vollbelegung herstellen, eine weitere Buchung als `unassigned` erzeugen, eine blockierende Buchung stornieren und prüfen, dass die ältere offene Buchung automatisch den freigewordenen Tisch erhält.
11. Eine zugewiesene Testbuchung bei vorhandener `TISCHE:`-Markierung in Zeitraum und `weight` ändern und prüfen, dass SQLite und Anny die neuen Werte und Tische enthalten.

## Anny-Webhook-Einstellungen

Im Anny-Adminbereich unter Account Settings → API muss genau ein aktiver Webhook für diese Integration bestehen:

- URL: produktiver HTTPS-Endpunkt mit aktuellem Secret
- Ereignisse: `bookings.created`, `bookings.updated`, `bookings.deleted`
- Einschränkung: Ressource `181227`
- nicht benötigt: `started`, `ended`, `checked-in`, `checked-out`

`bookings.deleted` umfasst laut offizieller Anny-Dokumentation auch Stornierungen. Nach dem Deployment die Call History auf HTTP 2xx prüfen. HTTP 503 ist nur bei temporären Anny-API- oder Rückschreibefehlern vorgesehen und löst die dokumentierten Wiederholungen aus. Doppelte Zustellungen derselben `event_id` werden ohne erneute Zuweisung mit HTTP 200 bestätigt.

Ein Deployment darf nicht stillschweigend eine leere Datenbank anlegen, wenn die bestehende Produktionsdatenbank erwartet wird.

## Rollback

Vor dem Wechsel müssen altes Image beziehungsweise alter Code, vorherige Konfiguration und Datenbank-Backup gemeinsam versioniert beschriftet werden. Bei Fehlern:

1. Webhook-Zustellung vorübergehend stoppen oder auf die vorige Instanz zeigen lassen.
2. Vorheriges Image mit unveränderter Konfiguration starten.
3. Nur wenn das Schema beziehungsweise die Daten verändert wurden, das geprüfte Datenbank-Backup zurückspielen.
4. Health, eine bekannte Zuweisung und Kollisionsfreiheit prüfen.

## Secret-Rotation

- Neuen Anny-Token erzeugen und produktiv hinterlegen.
- Dienst neu starten und einen reinen Lesezugriff testen.
- Alten Token widerrufen.
- Neues langes Webhook-Secret hinterlegen und in Anny konfigurieren.
- Eigenständige Dashboard-Zugangsdaten erzeugen; nicht den Webhook-Key wiederverwenden.
- Falls ein Secret in Logs oder Chat kopiert wurde, auch diese Kopien nach den geltenden Aufbewahrungsregeln behandeln.

Secrets nie als Kommandozeilenargument in eine gemeinsam sichtbare Shell-Historie schreiben. Für die lokale Entwicklung gehören sie ausschließlich in die ignorierte `.env` mit restriktiven Dateirechten.
