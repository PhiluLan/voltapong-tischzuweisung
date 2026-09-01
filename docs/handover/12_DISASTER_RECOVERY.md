# 12 – Disaster Recovery

## Szenario

Der DigitalOcean-Droplet einschließlich lokaler Disk und lokaler Backups existiert nicht mehr. Ziel ist, Webhook, Dashboard und verlässliche Tischzuweisung auf einem neuen Server wiederherzustellen.

## Aktuelle Recovery-Bewertung

Ein technischer Neuaufbau aus Git ist möglich. Ein vollständiger Datenneuaufbau ist **noch nicht garantiert**, weil kein automatisches, verifiziertes Offsite-Backup der SQLite-Datei und kein organisatorischer Secret-Manager nachgewiesen sind.

**RECOVERY GAP / HANDOVER BLOCKER:** Ohne Offsite-`allocator.db` fehlen Zuweisungs- und Idempotenzzustand. Der aktuelle Code besitzt keinen vollständigen Anny→SQLite-Rebuild. Lokale Backups auf dem verlorenen Droplet helfen nicht.

## Vorab organisatorisch festzulegen

| Punkt | Status |
| --- | --- |
| Incident Commander | xxx – organisatorisch festlegen |
| DigitalOcean/alternativer Provider-Owner | xxx – organisatorisch festlegen |
| GitHub Organization Owner | xxx – organisatorisch festlegen |
| Secret-/Backup-Owner | xxx – organisatorisch festlegen |
| DNS-/Domain-Admin | xxx – organisatorisch festlegen |
| Anny-Admin | xxx – organisatorisch festlegen |
| Business Owner für Buchungsstopp/manuelle Bearbeitung | xxx – organisatorisch festlegen |
| RTO | TODO – vor finaler Übergabe verifizieren und testen |
| RPO | TODO – vor finaler Übergabe verifizieren und testen |

## Benötigte unabhängige Recovery-Artefakte

- Zugriff auf GitHub und freigegebene Produktions-SHA
- verschlüsseltes Offsite-Backup von `allocator.db` inklusive Hash/Integritätsnachweis
- alle `.env`-Werte im organisatorischen Secret-Manager
- Backup-Entschlüsselungsschlüssel und Break-glass-Verfahren
- DigitalOcean-/Providerkonto mit Billing und MFA
- Domain-/DNS-Konto mit MFA
- Anny-Adminzugang
- dokumentierte SSH-/Firewall-/Serverbaseline
- Monitoring-/Alarmzugang

Wenn eines dieser Artefakte fehlt, die Lücke vor dem Start dokumentieren und Business Owner über manuellen Buchungsbetrieb informieren.

## Phase 1 – Incident stabilisieren

1. Droplet-Verlust im Providerkonto bestätigen; nicht nur DNS-/Caddyfehler annehmen.
2. Incident-Zeitpunkt, letzte erfolgreiche Webhookzustellung, letztes Backup und letzte Release-SHA erfassen.
3. Geschäftsbetrieb informieren. Neue Ping-Pong-Buchungen je nach Dauer kontrolliert pausieren oder manuell bearbeiten; Entscheidung liegt beim Business Owner.
4. Anny Call History ab Ausfallzeit sichern/markieren, ohne Secret-URL oder Kundendaten öffentlich zu exportieren.
5. Letztes Offsite-Backup anhand Hash, Zeit und `PRAGMA integrity_check` prüfen.
6. Keine alte IP/DNS-Information überschreiben, bevor Zielserver feststeht.

## Phase 2 – Neuen Server erstellen

Im organisatorischen Providerkonto:

1. unterstützten Ubuntu-24.04-LTS-Server in gewünschter Region anlegen; die verifizierte Baseline war `fra1`, 1 vCPU, ca. 1 GB RAM, 24 GB Disk.
2. mindestens zwei organisatorische Admin-SSH-Keys bereits beim Provisionieren hinterlegen.
3. Provider-MFA, Recovery und Billing bestätigen.
4. neue öffentliche IPv4 dokumentieren.
5. Serverzeit auf UTC belassen; fachliche App-Zeitzone bleibt `Europe/Zurich`.
6. Sicherheitsupdates aktivieren.
7. UFW zunächst so konfigurieren, dass 22 für Adminzugang und 80/443 für Caddy erreichbar sind; 8099 nicht öffentlich öffnen.

Servergröße ist die bisherige Baseline, keine universelle Garantie. Vor Go-live freien Speicher und RAM prüfen.

## Phase 3 – Docker und Grundschutz

Docker Engine und Compose Plugin nach der offiziellen Ubuntu-Anleitung installieren. Die beim Audit laufenden Versionen waren Docker 29.2.1 und Compose 5.1.0; für Recovery eine unterstützte Version verwenden und Kompatibilität mit `docker-compose.production.yml` prüfen.

```bash
docker version
docker compose version
ufw status numbered
ss -lntp
timedatectl
```

Offizielle Referenz: [Docker Engine auf Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

Keine unreviewten Convenience-Skripte als Root ausführen. Namentliche Adminbenutzer und SSH-Härtung gemäß [10_SECURITY_AND_SECRETS.md](10_SECURITY_AND_SECRETS.md) einrichten.

## Phase 4 – Repository und Release herstellen

```bash
RECOVERY_SHA=<verifizierte-produktions-sha>
install -d -m 0755 /opt/anny_webhook
git clone https://github.com/PhiluLan/voltapong-tischzuweisung.git /opt/anny_webhook
cd /opt/anny_webhook
git checkout --detach "$RECOVERY_SHA"
git status --short
git rev-parse HEAD
install -m 0644 docker-compose.production.yml docker-compose.yml
install -d -m 0700 data backups
```

Der GitHub-Pfad muss vor einer echten Übergabe auf den organisatorischen Repository-Owner aktualisiert werden. `git status --short` muss vor lokalen Recoverydateien leer sein; `.env` und `data/` sind ignoriert.

## Phase 5 – Konfiguration und Secrets bereitstellen

Aus dem organisatorischen Secret-Manager eine neue `/opt/anny_webhook/.env` mit Modus `0600` erzeugen. Niemals Werte aus Chat/alten Logs rekonstruieren.

Erforderliche Secret-Platzhalter:

```dotenv
ANNY_TOKEN=xxx
WEBHOOK_SECRET=xxx
DASHBOARD_PASSWORD=xxx
```

Nicht geheime Produktionswerte gegen [.env.example](../../.env.example) und [01_SYSTEM_OVERVIEW.md](01_SYSTEM_OVERVIEW.md) prüfen. Dashboard-Benutzer sollte ein Organisationsaccount sein.

```bash
chmod 0600 /opt/anny_webhook/.env
stat -c '%a %U:%G %n' /opt/anny_webhook/.env
sed -E '/^[[:space:]]*(#|$)/d; s/=.*$/=<configured>/' /opt/anny_webhook/.env
```

## Phase 6 – SQLite wiederherstellen

1. Offsite-Backup auf sicheren Transferweg laden.
2. SHA-256 gegen Backup-Protokoll prüfen.
3. `PRAGMA integrity_check` im Read-only-Modus ausführen.
4. als `/opt/anny_webhook/data/allocator.db` mit restriktiven Rechten installieren.
5. Backupzeit und erwartete Ereignislücke dokumentieren.

```bash
RESTORE_SOURCE=<absoluter-pfad-zum-geprüften-offsite-backup.db>
python3 - "$RESTORE_SOURCE" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
print(connection.execute('PRAGMA integrity_check').fetchone()[0])
print(connection.execute('SELECT name FROM sqlite_master WHERE type="table" ORDER BY name').fetchall())
connection.close()
PY
install -m 0600 "$RESTORE_SOURCE" /opt/anny_webhook/data/allocator.db
```

Nur bei `ok` fortfahren. Ohne DB-Backup nicht einfach eine leere DB als wiederhergestellt deklarieren; siehe [Recovery ohne SQLite-Backup](#recovery-ohne-sqlite-backup).

## Phase 7 – Image bauen und Anwendung intern starten

```bash
cd /opt/anny_webhook
docker compose -f docker-compose.yml config --quiet
docker build --label "org.opencontainers.image.revision=${RECOVERY_SHA}" --tag "anny_webhook-allocator:${RECOVERY_SHA}" .
docker tag "anny_webhook-allocator:${RECOVERY_SHA}" anny_webhook-allocator:latest
docker compose up -d allocator
docker compose ps
docker compose logs --tail=200 allocator
docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' anny_webhook-allocator-1
```

Vor öffentlichem Webhookverkehr DB-Integrität und Dashboarddaten intern prüfen. Es darf genau ein Allocator laufen.

## Phase 8 – Caddy und DNS

1. Caddyfile muss den bestehenden Host `webhook.voltabreau.ch` enthalten.
2. neue Server-IP und Firewall 80/443 prüfen.
3. A-Record im autorisierten DNS-Konto von alter auf neue IPv4 ändern.
4. autoritative Nameserver beobachten.
5. Caddy starten und Zertifikatslogs prüfen.

```bash
cd /opt/anny_webhook
docker compose up -d caddy
docker compose logs --since=10m caddy
dig +short webhook.voltabreau.ch A
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
```

Caddy-Volumes können leer beginnen; Caddy beschafft bei korrektem DNS/Ports ein neues Zertifikat. Keine alte Caddy-Datenkopie ist zwingend, DB und Secrets dagegen schon.

## Phase 9 – Anwendung und Dashboard prüfen

- beide Container running, Allocator healthy
- `/health` extern HTTP 200, `ok=true`, `database=true`, richtige Version
- OCI-Revision entspricht `RECOVERY_SHA`
- Dashboard ohne Zugang HTTP 401, mit Organisationszugang erreichbar
- keine Kollision und keine unerklärte zukünftige `unassigned`-Buchung
- RestartCount bleibt stabil
- Disk und Logs unauffällig

## Phase 10 – Anny Webhook und reale Testbuchung

1. Anny-Webhook bleibt auf `https://webhook.voltabreau.ch/?key=<WEBHOOK_SECRET>`; Secretwert nicht kopieren.
2. Webhook aktiv, Events create/update/delete, Restriction Ressource 181227 prüfen.
3. Call History ab Ausfallzeit erfassen.
4. gekennzeichnete reale Testbuchung in freigegebenem Slot anlegen.
5. HTTP 200, Tischangabe in Anny/E-Mail, SQLite/Dashboard und Kollisionsfreiheit prüfen.
6. Test stornieren und Freigabe prüfen.

## Phase 11 – Ereignislücke schließen

Das DB-Backup kann älter als der Ausfall sein. Anny wiederholt fehlgeschlagene Zustellungen nur begrenzt, und die App hat keinen Vollabgleich.

1. Zeitraum vom Backupzeitpunkt bis erfolgreichem Go-live bestimmen.
2. In Anny alle erstellten, geänderten und stornierten Ping-Pong-Buchungen dieses Zeitraums ermitteln.
3. Call History gegen `webhook_events`/Allocations abgleichen.
4. Fehlende Buchungen kontrolliert einzeln erneut zustellen oder durch ein reviewtes Recoverywerkzeug abgleichen.
5. Dashboard auf Kollisionen und offene Fälle prüfen.
6. Business Owner bestätigt die physische Belegung.

Ein vollständiges Recovery-/Reconciliation-Werkzeug existiert aktuell nicht. Manuelle Replays müssen idempotent und einzeln beobachtet werden.

## Recovery ohne SQLite-Backup

Dies ist kein Standardrestore, sondern ein schwerer Datenverlust.

1. Keine Verlässlichkeit der alten Tischlabels behaupten.
2. Neue Buchungen organisatorisch pausieren/manuell führen.
3. vollständigen relevanten zukünftigen Buchungsbestand aus Anny erheben.
4. separates, reviewtes Rebuild-/Importverfahren entwickeln und in isolierter Umgebung testen.
5. deterministische Neuzuweisung kann bisherige Tischlabels ändern; Betrieb und Kundenkommunikation einbeziehen.
6. erst nach Kollisions-/Vollständigkeitsprüfung produktiv freigeben.

**RECOVERY GAP:** Dieser Import ist nicht Teil des aktuellen Repositorys. Eine leere DB initialisiert zwar Schema, rekonstruiert aber keine vorhandenen Allocations.

## Abschlusskontrolle

- [ ] Provider-/Serverownership dokumentiert
- [ ] Release-SHA/Image-ID verifiziert
- [ ] `.env` aus Organisationsquelle, Rechte korrekt
- [ ] DB-Hash und Integrität `ok`
- [ ] Ereignislücke abgearbeitet
- [ ] DNS autoritativ auf neue IP
- [ ] TLS gültig und Caddy stabil
- [ ] `/health`, Docker Health und Dashboard erfolgreich
- [ ] Anny Testbuchung und Storno erfolgreich
- [ ] keine Kollision/offene unerklärte Buchung
- [ ] neues konsistentes Backup offsite
- [ ] Monitoring und Testalarm aktiv
- [ ] Incident-/Recoveryprotokoll und Folgeaufgaben abgeschlossen

## Noch vor Übergabe zu testen

- **HANDOVER BLOCKER:** vollständiger Neuaufbau durch Nachfolger mit eigenem Zugang
- **HANDOVER BLOCKER:** Offsite-DB/Secrets tatsächlich aus unabhängiger Quelle wiederherstellen
- **HANDOVER BLOCKER:** RTO/RPO messen und akzeptieren
- **HIGH PRIORITY:** Ereignislücken-/Reconciliation-Verfahren automatisieren oder als Tool implementieren
- **HIGH PRIORITY:** DNS-/TLS-/Anny-End-to-End-DR-Probe ohne Produktivrisiko planen
