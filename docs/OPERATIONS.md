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

Erst wenn der Vergleich zeigt, welche Version produktiv ist, darf der Git-Stand als Deployment-Quelle übernommen werden.

## Lokal prüfen

```bash
cp .env.example .env
# Dummy- oder Entwicklungswerte setzen
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
docker compose config --quiet
docker compose build
```

Für einen lokalen Lauf mit echten Anny-Zugangsdaten muss der Webhook so geschützt sein, dass keine fremden Buchungs-IDs verarbeitet werden können.

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
3. Bestehende Datenbank als Volume einbinden.
4. Container bauen und starten.
5. Intern `/health` prüfen, dann einen kontrollierten Test-Webhook verwenden.
6. `/allocations` darf am öffentlichen Reverse Proxy nicht frei erreichbar sein.
7. Logs und Anny-Buchung des kontrollierten Tests prüfen.

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
- Falls ein Secret in Logs oder Chat kopiert wurde, auch diese Kopien nach den geltenden Aufbewahrungsregeln behandeln.

Secrets nie als Kommandozeilenargument in eine gemeinsam sichtbare Shell-Historie schreiben. Für die lokale Entwicklung gehören sie ausschließlich in die ignorierte `.env` mit restriktiven Dateirechten.
