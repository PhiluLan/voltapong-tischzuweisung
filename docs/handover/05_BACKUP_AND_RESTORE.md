# 05 – Backup and Restore

Stand: 1. September 2026

## Kurzurteil

Konsistente manuelle SQLite-Backups wurden nachgewiesen, liegen aber auf demselben Droplet wie Produktion. Es ist kein automatisches, verschlüsseltes Offsite-Backup und kein vollständiger Restore-Test durch eine zweite Person verifiziert.

**HANDOVER BLOCKER:** Ein Droplet-Verlust kann derzeit sowohl Produktionsdatenbank als auch die bekannten lokalen Backups vernichten. Die aktuelle Anwendung kann den vollständigen SQLite-Zustand nicht automatisch aus Anny neu aufbauen.

## Was muss gesichert werden?

| Objekt | Warum | Quelle | Ziel |
| --- | --- | --- | --- |
| `allocator.db` | aktuelle Tischbelegung und Event-Idempotenz | `/opt/anny_webhook/data/allocator.db` | konsistentes, verschlüsseltes Offsite-Backup |
| Produktionskonfiguration | nicht geheime Werte und Laufzeitparameter | `/opt/anny_webhook/.env` | organisatorischer Secret-Manager beziehungsweise verschlüsselte Konfigurationssicherung |
| Secrets | Anny-Token, Webhook-Secret, Dashboard-Credential | Provider/Secret-Manager | organisatorischer Secret-Manager, nicht Git |
| Release-SHA/Image-ID | reproduzierbares Rollback | Git/Docker/Release-Protokoll | Release-Protokoll und optional Image-Registry |
| Compose/Caddy/Code | Serverneubau | GitHub | GitHub; Hash gegen Release prüfen |
| DNS-/Providerkonfiguration | Wiederaufbau und Ownership | Providerkonten | dokumentierte, secretfreie Export-/Inventarliste |

Caddy-Zertifikatsvolumes sind nützlich, aber nicht zwingend: Caddy kann Zertifikate bei korrektem DNS und erreichbaren Ports neu beziehen. Sie ersetzen keine Datenbank- oder Secret-Sicherung.

## Verifizierte lokale Sicherungen

Beim Audit bestanden unter anderem:

- `/opt/anny_webhook/backups/20260901T194300Z-pre-v3/`
- `/opt/anny_webhook/backups/20260901T195900Z-postdeploy-pre-e2e.db`
- `/opt/anny_webhook/backups/20260901T203752Z-pre-dashboard-credentials/.env`

Die geprüften SQLite-Dateien meldeten `PRAGMA integrity_check = ok`. Diese Sicherungen sind manuell, lokal und keine belastbare Disaster-Recovery-Lösung. Die `.env`-Sicherung enthält Secrets und muss wie ein Credential behandelt werden.

## Aktueller versus erforderlicher Sicherungsstand

| Eigenschaft | Bereits vorhanden | Für Übergabereife erforderlich |
| --- | --- | --- |
| konsistente SQLite-Kopie | manuell vor Rollout/E2E | automatisch mindestens täglich und vor jedem Release |
| Integritätsprüfung | bei bekannten Backups manuell | bei jedem Lauf plus Alarm bei Fehler |
| lokale Aufbewahrung | einzelne Vorher-Backups | definierte Rotation |
| Offsite-Kopie | nicht verifiziert | verschlüsselt, automatisiert, anderer Failure Domain |
| Droplet-Backup | nicht im Providerkonto verifiziert | aktivieren oder bewusste dokumentierte Alternative |
| Restore-Test | isolierter Smoke-Test auf DB-Kopie; kein vollständiger Nachfolger-Restore | mindestens quartalsweise in isolierter Umgebung |
| Erfolgsalarm | nicht verifiziert | Alarm bei ausbleibendem/fehlerhaftem Backup |

## Zielvorgabe, noch nicht implementiert

Die folgende Policy ist eine empfohlene Übergabeanforderung, **kein behaupteter Ist-Zustand**:

- täglich konsistentes SQLite-Backup, mindestens 30 tägliche Stände
- vor jedem Deployment und jeder Secret-/Konfigurationsänderung zusätzlicher Stand
- 12 monatliche Stände oder organisatorisch freigegebene gleichwertige Retention
- verschlüsselte Offsite-Kopie in einem von Volta Bräu kontrollierten Account
- täglicher Hash-/Integritätsnachweis und Alarm bei Ausfall
- quartalsweiser Restore-Test
- RPO und RTO organisatorisch festlegen; Vorschlag erst nach gemessenen Restore-Tests bestätigen

## Konsistentes SQLite-Backup erstellen

Nicht die geöffnete `allocator.db` roh mit `cp` kopieren. Die SQLite-Backup-API erzeugt bei laufendem Dienst einen konsistenten Snapshot.

```bash
cd /opt/anny_webhook
BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP_DB="/data/.allocator-${BACKUP_STAMP}.db"

docker compose exec -T allocator python - "$TMP_DB" <<'PY'
import sqlite3
import sys

target = sys.argv[1]
source = sqlite3.connect('/data/allocator.db', timeout=30)
destination = sqlite3.connect(target)
with destination:
    source.backup(destination)
destination.close()
source.close()
PY

install -d -m 0700 /opt/anny_webhook/backups
mv "/opt/anny_webhook/data/.allocator-${BACKUP_STAMP}.db" "/opt/anny_webhook/backups/${BACKUP_STAMP}-allocator.db"
chmod 0600 "/opt/anny_webhook/backups/${BACKUP_STAMP}-allocator.db"

python3 - "/opt/anny_webhook/backups/${BACKUP_STAMP}-allocator.db" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
print(connection.execute('PRAGMA integrity_check').fetchone()[0])
print(connection.execute('SELECT status, count(*) FROM allocations GROUP BY status ORDER BY status').fetchall())
connection.close()
PY

sha256sum "/opt/anny_webhook/backups/${BACKUP_STAMP}-allocator.db"
stat -c '%a %U:%G %s %y %n' "/opt/anny_webhook/backups/${BACKUP_STAMP}-allocator.db"
```

Nur ein Ergebnis `ok` ist akzeptabel. Hash, Größe, Zeit, Release-SHA und Offsite-Uploadstatus ins Backup-Protokoll übernehmen, nicht den Dateninhalt.

Danach die Datei mit dem organisatorisch festgelegten Backup-Werkzeug verschlüsselt offsite replizieren. Das konkrete Werkzeug und Ziel sind noch nicht verifiziert:

**TODO – vor finaler Übergabe verifizieren:** Offsite-Provider, Verschlüsselungsverfahren, Key-Owner, Uploadbefehl, Retention und Alarmierung.

## Konfiguration sichern

Die `.env` enthält echte Secrets. Sie darf:

- nicht in Git,
- nicht unverschlüsselt in Cloud Storage,
- nicht in ein Ticket oder einen Chat,
- nicht als Shell-Ausgabe in ein Protokoll.

Zielzustand: Alle Werte werden einzeln im organisatorischen Secret-Manager geführt; `.env` ist nur eine restriktive Deploymentkopie mit Modus `0600`. Für die Rekonstruktion müssen mindestens diese Schlüssel bekannt sein, Werte hier nur als Platzhalter:

```dotenv
ANNY_BASE=https://b.anny.co/api/v1
ANNY_TOKEN=xxx
ANNY_TZ=Europe/Zurich
ALLOCATOR_DB=/data/allocator.db
ALLOCATE_RESOURCE_IDS=181227
TABLE_LABELS=Tisch 1,Tisch 2,Tisch 3,Tisch 4,Tisch 5,Tisch 6,Tisch 7,Tisch 8
HANDLE_UPDATED=1
REDISTRIBUTION_LIMIT=20
WEBHOOK_EVENT_RETENTION_DAYS=90
AUTO_MARKER=TISCHE:
AUTO_PREFIX=Auto-Allocation:
WEBHOOK_SECRET=xxx
DASHBOARD_USERNAME=<ORGANISATIONS-ACCOUNT>
DASHBOARD_PASSWORD=xxx
DASHBOARD_REFRESH_SECONDS=30
DEBUG=0
```

## Backup-Integrität regelmäßig prüfen

Ein Backup ist erst belastbar, wenn drei Prüfungen erfolgreich sind:

1. Datei ist vorhanden, nicht leer, restriktiv lesbar und Hash stimmt.
2. `PRAGMA integrity_check` liefert `ok`.
3. Ein isolierter Restore startet die Anwendung auf einer Kopie, ohne Verbindung zu produktiven Webhooks oder schreibender Anny-API.

Ein erfolgreiches Droplet-Snapshot allein beweist keine konsistente offene SQLite-Datei. Deshalb SQLite-Snapshot zuerst per Backup-API erzeugen und den Droplet-/Offsite-Mechanismus diesen Snapshot erfassen lassen.

## Restore – Vorbereitung für alle Szenarien

Vor jedem Restore:

- Incident-Zeitpunkt und Grund dokumentieren.
- aktuelle DB nach Möglichkeit erneut konsistent sichern; bei Beschädigung zumindest Dateien unverändert quarantänisieren.
- gewünschtes Backup anhand Zeit, Hash und Integritätscheck eindeutig identifizieren.
- Auswirkungen des RPO bestimmen: Welche Webhooks/Buchungen liegen nach dem Backup?
- Schreibende Anny-Tests und parallele Deployments stoppen.
- niemals ein Backup „auf Verdacht“ über die einzige Kopie schreiben.

## Restore-Szenario 1: SQLite-Problem

### A. Backup vorab prüfen

```bash
RESTORE_SOURCE=<absoluter-pfad-zum-verifizierten-backup.db>
python3 - "$RESTORE_SOURCE" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
print(connection.execute('PRAGMA integrity_check').fetchone()[0])
print(connection.execute('SELECT name FROM sqlite_master WHERE type="table" ORDER BY name').fetchall())
connection.close()
PY
sha256sum "$RESTORE_SOURCE"
```

Nur mit `ok` und den Tabellen `allocations`/`webhook_events` fortfahren.

### B. Allocator stoppen und alte Dateien recoverable sichern

```bash
cd /opt/anny_webhook
RESTORE_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
QUARANTINE_DIR="/opt/anny_webhook/backups/${RESTORE_STAMP}-failed-db"
install -d -m 0700 "$QUARANTINE_DIR"
docker compose stop allocator

for DB_FILE in data/allocator.db data/allocator.db-wal data/allocator.db-shm; do
  if [ -e "$DB_FILE" ]; then
    mv "$DB_FILE" "$QUARANTINE_DIR/"
  fi
done
```

Das Verschieben ist absichtlich recoverable. `-wal` und `-shm` niemals bei laufendem Prozess löschen.

### C. Backup installieren und starten

```bash
install -m 0600 "$RESTORE_SOURCE" /opt/anny_webhook/data/allocator.db
chown --reference=/opt/anny_webhook/data /opt/anny_webhook/data/allocator.db
docker compose up -d --no-build allocator
docker compose ps
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
docker compose logs --since=10m allocator
```

Anschließend Dashboard auf Kollisionen/offene Fälle prüfen und alle Buchungen seit Backup-Zeitpunkt anhand Anny Call History gezielt abgleichen. Doppelte alte `event_id`-Zustellungen können abhängig vom Backup erneut verarbeitet werden; deshalb besonders auf Anny-Notizen und Kollisionen achten.

### D. Abschluss

- Restore-Quelle/Hash, Zeit und Datenlücke protokollieren.
- Kontrollierte Testbuchung durchführen.
- Quarantäne nicht löschen, bevor Incident abgeschlossen und Datenschutzaufbewahrung geklärt ist.
- Neues konsistentes Backup erstellen und offsite replizieren.

## Restore-Szenario 2: Fehlerhaftes Deployment

1. Erst Anwendung gemäß [Rollback](04_DEPLOYMENT.md#rollback) auf vorheriges Image/Dateien zurücksetzen.
2. Bestehende DB beibehalten, wenn `integrity_check=ok` und das alte Image sie lesen kann.
3. Nur bei nachgewiesener Datenbeschädigung/Inkompatibilität Szenario 1 ausführen.
4. Bei DB-Restore alle seit dem Backup eingegangenen Anny-Buchungen einzeln abgleichen.

Ein unnötiger DB-Restore erzeugt Datenverlust und ist kein Standardbestandteil eines Code-Rollbacks.

## Restore-Szenario 3: Vollständiger Serververlust

Der vollständige Ablauf steht in [12_DISASTER_RECOVERY.md](12_DISASTER_RECOVERY.md). Benötigt werden unabhängig vom verlorenen Droplet:

- GitHub-Repository und freigegebene Release-SHA
- organisatorische Secrets/`.env`-Werte
- verifiziertes Offsite-Backup der SQLite-Datei
- DigitalOcean- oder alternativer Providerzugang
- Domain-/DNS-Adminzugang
- Anny-Adminzugang

Fehlt die Offsite-DB, kann der heutige Allocator nicht zuverlässig den vollständigen Stand aus Anny neu erzeugen. Dann bleibt nur ein kontrollierter manueller/neu zu entwickelnder Rebuild und die Tischzuweisung darf bis zum Abgleich nicht als verlässlich gelten.

## Nicht tun

- keine rohe Kopie der geöffneten SQLite-Datei als einziges Backup
- keine `rm`-Befehle auf DB, WAL, SHM oder Backupverzeichnisse während eines Incidents
- kein `docker system prune` vor Sicherung der Rollback-Images
- keine `.env` in Git oder unverschlüsselten Offsite-Speicher
- kein Restore direkt in Produktion ohne vorherigen Integritätscheck
- keine Annahme, dass Anny sämtliche lokalen Tischlabels automatisch rekonstruieren kann
