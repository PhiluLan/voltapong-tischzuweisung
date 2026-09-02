# 04 – Deployment and Rollback

Stand: 2. September 2026

## Aktueller Deployment-Mechanismus

Es gibt keine CI/CD-Workflowdatei und ein Push nach GitHub verändert Produktion nicht. Der aktuelle Mechanismus ist ein kontrolliertes manuelles Release:

1. exakten Git-Commit lokal prüfen,
2. Tests ausführen,
3. Dateien in ein separates Release-Verzeichnis auf dem Droplet übertragen,
4. neues Docker-Image mit Commit-Revision bauen,
5. konsistentes SQLite-Backup und Pre-Deployment-Artefakte sichern,
6. freigegebene Dateien unter `/opt/anny_webhook` installieren,
7. Allocator-Container auf das neue Image umschalten,
8. Health, Logs, Dashboard und Anny End-to-End prüfen.

Der produktive Anwendungscode basiert seit dem 2. September 2026 auf `6937aa89b9afb2c58409eb591fd4c952a70684ef`. Repository-`main` kann danach zusätzliche Dokumentationscommits enthalten. Maßgeblich ist immer die explizit freigegebene Release-SHA, nicht „der neueste Stand“.

**HIGH PRIORITY:** Dieses Verfahren muss vor der Übergabe von einer zweiten Person in einer sicheren Umgebung beziehungsweise bei einem kontrollierten Release vollständig geprobt werden. Die Befehle unten entsprechen der verifizierten Topologie; ein automatisierter Release-Workflow existiert noch nicht.

## Regeln vor jedem Release

- Nie direkt in `app.py` auf dem Server editieren.
- Nie `.env`, `data/` oder `backups/` aus einem lokalen Checkout hochladen.
- Nie mit einer leeren Datenbank starten, wenn die Produktionsdatenbank erwartet wird.
- Nie mehr als einen Allocator-Container/Worker gleichzeitig starten.
- Keine echte Buchung als Testobjekt verwenden, ohne sie eindeutig zu kennzeichnen und anschließend fachlich zu bereinigen.
- Vor jedem Umschalten: DB-Backup, altes Image, alter Commit und referenzierte Secret-/Konfigurationsversion festhalten.
- Ein fehlerhafter Healthcheck ist ein fehlgeschlagenes Deployment, kein Anlass, die Prüfung zu überspringen.

## 1. Voraussetzungen prüfen

Benötigt werden:

- Adminzugriff auf das GitHub-Repository
- namentlicher SSH-Zugang zum Droplet
- Zugriff auf den organisatorischen Secret-Manager, ohne Secret-Werte in die Shell-Historie zu kopieren
- Anny-Adminzugang für Call History und kontrollierten Test
- verifizierter Offsite-Backupzugriff
- freigegebenes Wartungsfenster und benannter Rollback-Entscheider

Lokal:

```bash
git fetch --all --prune
git status --short
git rev-parse <RELEASE_SHA>
git log -1 --oneline <RELEASE_SHA>
git diff --stat 6937aa89b9afb2c58409eb591fd4c952a70684ef..<RELEASE_SHA> -- app.py Dockerfile requirements.txt templates docker-compose.production.yml Caddyfile
```

`git status --short` muss für einen unveränderten Release-Checkout leer sein. `<RELEASE_SHA>` muss ein vollständiger, reviewter Commit sein.

## 2. Produktionszustand prüfen

Read-only auf dem Server:

```bash
ssh <ADMIN_USER>@138.68.87.128
cd /opt/anny_webhook
docker compose ps
docker inspect --format 'image={{.Image}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} restarts={{.RestartCount}}' anny_webhook-allocator-1
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$(docker inspect --format '{{.Image}}' anny_webhook-allocator-1)"
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
df -h /
```

Die laufende Revision, Image-ID, Health-Antwort und freie Platte kommen in das Release-Protokoll. Wenn Health nicht grün ist, zuerst den vorhandenen Incident lösen; nicht darüber deployen.

## 3. Backup erstellen

Die konsistente Prozedur steht in [05_BACKUP_AND_RESTORE.md](05_BACKUP_AND_RESTORE.md#konsistentes-sqlite-backup-erstellen). Das Backup muss:

- `PRAGMA integrity_check = ok` liefern,
- einen SHA-256-Hash besitzen,
- außerhalb des Droplets repliziert sein,
- für den verantwortlichen Nachfolger zugänglich sein.

Zusätzlich vor dem Umschalten sichern:

- aktuelle Image-ID und OCI-Revision
- `app.py`, `Dockerfile`, `requirements.txt`, `templates/`, `docker-compose.yml`, `Caddyfile`
- Dateimetadaten und organisatorische Secret-Manager-Version der `.env`, aber niemals ihren Inhalt im Release-Protokoll
- Hash und Dateigröße der Datenbank

## 4. Richtigen Git-Stand auswählen und testen

In einem separaten, sauberen Checkout:

```bash
git switch --detach <RELEASE_SHA>
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m py_compile app.py
docker compose -f docker-compose.production.yml config --quiet
```

Die Tests verwenden Dummy-Credentials und dürfen nicht gegen Produktion laufen. Der geprüfte Stand von Version 3.1.0 umfasst 39 Tests.

## 5. Release übertragen und Image bauen

Auf dem Server ein unverwechselbares Staging-Verzeichnis anlegen:

```bash
RELEASE_SHA=<vollständige-git-sha>
RELEASE_DIR="/opt/anny_webhook/releases/${RELEASE_SHA}"
install -d -m 0750 "$RELEASE_DIR/templates"
```

Vom lokalen, sauberen Checkout nur diese Dateien übertragen:

```bash
RELEASE_SHA=<dieselbe-vollständige-git-sha>
REMOTE_RELEASE_DIR="/opt/anny_webhook/releases/${RELEASE_SHA}"
scp app.py Dockerfile requirements.txt Caddyfile docker-compose.production.yml <ADMIN_USER>@138.68.87.128:"${REMOTE_RELEASE_DIR}/"
scp templates/dashboard.html <ADMIN_USER>@138.68.87.128:"${REMOTE_RELEASE_DIR}/templates/"
```

Keine `.env` übertragen. Auf dem Server Dateihashes mit dem lokalen Checkout vergleichen. Dann im Release-Verzeichnis bauen:

```bash
cd "$RELEASE_DIR"
docker build --label "org.opencontainers.image.revision=${RELEASE_SHA}" --tag "anny_webhook-allocator:${RELEASE_SHA}" .
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}} {{.Id}}' "anny_webhook-allocator:${RELEASE_SHA}"
```

Wenn `Caddyfile` geändert wurde, vor Installation isoliert validieren:

```bash
docker run --rm --volume "$RELEASE_DIR/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile
```

## 6. Neue Version installieren und Container starten

Vorher den aktuellen Rollback-Zeiger festhalten:

```bash
DEPLOY_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CURRENT_IMAGE_ID="$(docker inspect --format '{{.Image}}' anny_webhook-allocator-1)"
docker tag "$CURRENT_IMAGE_ID" "anny_webhook-allocator:rollback-${DEPLOY_STAMP}"
PREDEPLOY_DIR="/opt/anny_webhook/backups/${DEPLOY_STAMP}-predeploy"
install -d -m 0700 "$PREDEPLOY_DIR/templates"
install -m 0644 /opt/anny_webhook/app.py /opt/anny_webhook/Dockerfile /opt/anny_webhook/requirements.txt /opt/anny_webhook/docker-compose.yml /opt/anny_webhook/Caddyfile "$PREDEPLOY_DIR/"
install -m 0644 /opt/anny_webhook/templates/dashboard.html "$PREDEPLOY_DIR/templates/"
stat -c '%a %U:%G %s %y %n' /opt/anny_webhook/.env > "$PREDEPLOY_DIR/env.metadata"
```

Die `.env` wird bewusst nicht in dieses unverschlüsselte Code-Backup kopiert. Ihre wiederherstellbare, verschlüsselte Organisationskopie muss bereits im Secret-Manager existieren.

Freigegebene Dateien installieren:

```bash
install -m 0644 "$RELEASE_DIR/app.py" /opt/anny_webhook/app.py
install -m 0644 "$RELEASE_DIR/Dockerfile" /opt/anny_webhook/Dockerfile
install -m 0644 "$RELEASE_DIR/requirements.txt" /opt/anny_webhook/requirements.txt
install -m 0644 "$RELEASE_DIR/docker-compose.production.yml" /opt/anny_webhook/docker-compose.yml
install -m 0644 "$RELEASE_DIR/Caddyfile" /opt/anny_webhook/Caddyfile
install -d -m 0755 /opt/anny_webhook/templates
install -m 0644 "$RELEASE_DIR/templates/dashboard.html" /opt/anny_webhook/templates/dashboard.html
docker tag "anny_webhook-allocator:${RELEASE_SHA}" anny_webhook-allocator:latest
cd /opt/anny_webhook
docker compose up -d --no-build --no-deps --force-recreate allocator
```

Nur bei einer geprüften Caddy-Änderung:

```bash
docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
```

## 7. Healthcheck durchführen

```bash
cd /opt/anny_webhook
docker compose ps
docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' anny_webhook-allocator-1
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$(docker inspect --format '{{.Image}}' anny_webhook-allocator-1)"
```

Erwartet: Allocator `healthy`, HTTP 200, `ok=true`, richtige Anwendungsversion und exakt die freigegebene Revision.

## 8. Logs kontrollieren

```bash
docker compose logs --since=10m allocator
docker compose logs --since=10m caddy
docker inspect --format 'restarts={{.RestartCount}}' anny_webhook-allocator-1
```

Keine wiederholten Startfehler, SQLite-Fehler, 5xx-Schleifen oder Restarts akzeptieren. Logausschnitte vor Weitergabe auf Secrets, Query-Parameter und Buchungsdaten prüfen.

## 9. Dashboard prüfen

1. `https://webhook.voltabreau.ch/dashboard` ohne Zugang öffnen: HTTP 401 muss erscheinen.
2. Mit Zugang aus dem Secret-Manager anmelden; niemals Passwort in eine gemeinsam sichtbare Kommandozeile schreiben.
3. Aktualisierungszeit, Container-/DB-nahe Kennzahlen, Kollisionen und Webhookfehler prüfen.
4. Eine gelbe Ampel nicht pauschal als Deploymentfehler werten; konkrete Ursache in `issues` prüfen.
5. Rot ist ein Release-Stopper.

## 10. Anny-Test durchführen

In einem freigegebenen zukünftigen Zeitfenster:

1. eindeutig bezeichnete Testbuchung anlegen,
2. in Anny Call History HTTP 2xx für den Webhook prüfen,
3. in Buchung und Bestätigung „Deine Tische“ prüfen,
4. SQLite/Dashboard auf `assigned` und Kollisionsfreiheit prüfen,
5. Testbuchung stornieren,
6. Webhook und Freigabe erneut prüfen,
7. Testdaten fachlich sauber beenden.

Vor größeren Logikänderungen zusätzlich den dokumentierten Vollbelegungs-/Warteschlangen-/Storno-Test aus [HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) durchführen.

## 11. Erfolg bestätigen

Im Release-Protokoll festhalten:

- Release-SHA und Image-ID
- Zeit, ausführende und freigebende Person
- Backup-Datei, SHA-256, Offsite-Ziel und Integritätsstatus
- vorherige Image-ID/Rollback-Tag
- Test-/Health-/Dashboard-/Anny-Ergebnis
- beobachtete Warnungen und Entscheidung

Keine Secrets, Kundennamen, vollständigen Payloads oder privaten Daten protokollieren.

## Rollback

Rollback ist erforderlich, wenn Health/Start fehlschlägt, neue Kollisionen entstehen, Webhooks dauerhaft 5xx liefern oder der kontrollierte Anny-Test scheitert.

### Anwendung zurückrollen

1. Incident-Zeit und betroffene Release-SHA festhalten.
2. **Vor dem Rollback erneut ein konsistentes DB-Backup erstellen**, auch wenn die aktuelle Version fehlerhaft ist.
3. Variablen anhand des Pre-Deployment-Protokolls setzen, niemals raten:

```bash
cd /opt/anny_webhook
ROLLBACK_TAG=<verifiziertes-rollback-tag>
PREDEPLOY_DIR=<verifiziertes-predeploy-verzeichnis>
docker image inspect "$ROLLBACK_TAG"
```

4. Vorherige Code-/Compose-Dateien wieder installieren, `.env` und `data/` nicht überschreiben:

```bash
install -m 0644 "$PREDEPLOY_DIR/app.py" /opt/anny_webhook/app.py
install -m 0644 "$PREDEPLOY_DIR/Dockerfile" /opt/anny_webhook/Dockerfile
install -m 0644 "$PREDEPLOY_DIR/requirements.txt" /opt/anny_webhook/requirements.txt
install -m 0644 "$PREDEPLOY_DIR/docker-compose.yml" /opt/anny_webhook/docker-compose.yml
install -m 0644 "$PREDEPLOY_DIR/Caddyfile" /opt/anny_webhook/Caddyfile
install -m 0644 "$PREDEPLOY_DIR/templates/dashboard.html" /opt/anny_webhook/templates/dashboard.html
docker tag "$ROLLBACK_TAG" anny_webhook-allocator:latest
docker compose up -d --no-build --no-deps --force-recreate allocator
```

5. Health, Revision, Logs, Dashboard und kontrollierten Anny-Test wie oben prüfen.

### Datenbank nur bei nachgewiesener Notwendigkeit zurückrollen

Ein Code-Rollback erfordert nicht automatisch einen DB-Rollback. Die aktuelle Migration ist additiv; ein unnötiger DB-Restore würde reale Buchungsereignisse nach dem Backup verlieren.

Nur bei bestätigter DB-Beschädigung oder nachgewiesener Inkompatibilität die Restore-Anleitung in [05_BACKUP_AND_RESTORE.md](05_BACKUP_AND_RESTORE.md#restore-szenario-1-sqlite-problem) verwenden. Vorher Ereignislücke und betroffene Buchungen dokumentieren und anschließend in Anny manuell abgleichen.

### Nicht tun

- kein `docker system prune`, um „Platz zu schaffen“, bevor Rollback-Images gesichert sind
- kein Löschen von `allocator.db`, `-wal` oder `-shm`
- keine leere Datenbank als scheinbar erfolgreichen Start akzeptieren
- nicht gleichzeitig alte und neue Allocator-Instanz auf dieselbe oder getrennte DBs loslassen
- nicht das Webhook-Secret oder Token als schnelle Fehlerbehebung deaktivieren

## Deployment-Lücken

- **HIGH PRIORITY:** kein automatischer CI-Test/Build/Deploy und kein unveränderliches Registry-Artefakt
- **HIGH PRIORITY:** kein durch Nachfolger dokumentiert durchgeführter Rollbacktest
- **HANDOVER BLOCKER:** kein nachgewiesener Offsite-Backup-/Restorepfad vor einem Release
- **TODO – vor finaler Übergabe verifizieren:** exakte Aufbewahrung und Kennzeichnung der Release-/Rollback-Images auf dem Server
