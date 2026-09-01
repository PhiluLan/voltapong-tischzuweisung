# 06 – Incident Runbook

Stand: 1. September 2026

## Verwendung

Dieses Runbook beginnt mit sicheren Diagnosemaßnahmen. Produktionsänderungen erfolgen nur mit benanntem Incident-Verantwortlichen, aktuellem Backup und dokumentierter Rückfalloption.

Für jeden Incident zuerst erfassen:

- Beginn, Zeitzone und meldende Person
- betroffene Buchungsnummern und Zeitfenster, ohne Kundendaten in öffentliche Tickets zu kopieren
- letzte bekannte funktionierende Zeit
- letzte Deployment-/Secret-/DNS-/Anny-Änderung
- `/health`, Docker-Status, Dashboardfarbe und Anny Call History

Standarddiagnose:

```bash
cd /opt/anny_webhook
date -u
uptime
df -h /
docker compose ps
docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} restarts={{.RestartCount}}' anny_webhook-allocator-1
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
docker compose logs --since=30m --tail=300 allocator
docker compose logs --since=30m --tail=300 caddy
```

Logausgaben vor Weitergabe auf Query-Secrets, Tokens, Buchungs- und Kundendaten prüfen.

## Dashboard Gelb

**SYMPTOM**

Dashboard zeigt Warnzustand, Dienst kann trotzdem erreichbar sein.

**Wahrscheinliche Ursachen**

Zukünftige `unassigned`-Buchung, retry-fähiger Webhookfehler der letzten 24 Stunden, ungültige Zeitdaten oder leere DB. Historische Einträge allein sind nur relevant, wenn sie laut Dashboard noch zukünftig/aktiv sind.

**PRÜFEN**

1. Im Dashboard Abschnitt „Probleme“ statt nur die Farbe lesen.
2. `/health` und Containerzustand prüfen.
3. Betroffene Buchung in Anny öffnen und Tischbedarf, Zeitraum, Status und Notizen prüfen.
4. Anny Call History auf letzten HTTP-Status prüfen.

**MASSNAHME**

Kapazitätsfall fachlich prüfen; retry-fähigen Fehler erst nach Behebung der Ursache kontrolliert erneut zustellen. Bei tatsächlich freier Kapazität Reconciliation/Stornozustellung untersuchen. Ungültige Zeitdaten in Anny korrigieren, nicht in SQLite.

**NICHT TUN**

Keine `unassigned`-Zeile löschen oder manuell auf `assigned` setzen. Gelb nicht ohne Sichtung ignorieren.

**ESKALIEREN WENN**

Eine bevorstehende Buchung trotz physisch freiem Tisch offen bleibt, Fehler wiederkehrt oder Ursache nicht eindeutig ist.

## Dashboard Rot

**SYMPTOM**

Dashboard meldet mindestens eine überschneidende Tischkollision.

**Wahrscheinliche Ursachen**

Parallelbetrieb mehrerer Allocator-Instanzen/Worker, manuelle DB-/Anny-Änderung, fehlerhafter Restore oder Logikregression.

**PRÜFEN**

```bash
cd /opt/anny_webhook
docker compose ps
docker ps --filter name=anny_webhook --format '{{.Names}} {{.Image}} {{.Status}}'
docker inspect --format '{{.Config.Cmd}}' anny_webhook-allocator-1
```

Kollisionspaare im Dashboard sichern und beide Buchungen in Anny vergleichen.

**MASSNAHME**

Incident-Verantwortlichen und Betrieb informieren, neue Buchungen für den betroffenen Zeitraum organisatorisch pausieren und Tischbelegung manuell sicherstellen. Prüfen, ob genau ein Worker läuft. Letzte Änderung gegebenenfalls gemäß [Rollback](04_DEPLOYMENT.md#rollback) zurückrollen. Datenkorrektur erst nach Backup und Ursachenanalyse.

**NICHT TUN**

Keine der Buchungen automatisch stornieren, keine DB-Zeilen auf Verdacht löschen, keinen zweiten Container zum „Abgleich“ starten.

**ESKALIEREN WENN**

Immer sofort; Rot ist ein betrieblicher Sicherheitsfehler.

## `/health` nicht erreichbar

**SYMPTOM**

Timeout, DNS-/TLS-Fehler, HTTP 502/503 oder keine JSON-Antwort.

**Wahrscheinliche Ursachen**

Server/Netzwerk, DNS/TLS, Caddy, unhealthy Allocator, SQLite oder volle Platte.

**PRÜFEN**

```bash
dig +short webhook.voltabreau.ch A
curl -v --max-time 10 https://webhook.voltabreau.ch/health
ssh <ADMIN_USER>@138.68.87.128
cd /opt/anny_webhook
docker compose ps
docker compose logs --since=30m caddy allocator
```

**MASSNAHME**

Fehler entlang Domain → Caddy → Allocator → SQLite eingrenzen und passenden Abschnitt dieses Runbooks verwenden.

**NICHT TUN**

Nicht sofort Server rebooten; damit verschwinden Diagnoseinformationen und eine beschädigte DB wird nicht repariert.

**ESKALIEREN WENN**

Mehr als fünf Minuten Produktionsausfall, fehlender Serverzugang oder Ursache DB/Netzwerk nicht sicher behebbar.

## Allocator unhealthy

**SYMPTOM**

Compose zeigt `unhealthy`, Caddy liefert oft 502/503.

**Wahrscheinliche Ursachen**

App startet nicht, fehlende/ungültige Env-Variable, DB nicht les-/schreibbar, leeres/falsches Volume, Pythonfehler oder Ressourcenmangel.

**PRÜFEN**

```bash
cd /opt/anny_webhook
docker compose ps allocator
docker inspect --format '{{json .State.Health}}' anny_webhook-allocator-1
docker compose logs --since=30m --tail=300 allocator
docker inspect --format '{{json .Mounts}}' anny_webhook-allocator-1
stat -c '%a %U:%G %s %n' data/allocator.db .env
```

**MASSNAHME**

Bei Releasefehler rollback. Bei DB-Fehler Integrität read-only prüfen und [Restore](05_BACKUP_AND_RESTORE.md#restore-szenario-1-sqlite-problem) verwenden. Bei fehlender Konfiguration Secret-Manager gegen Env-Schlüsselnamen prüfen, ohne Werte auszugeben.

**NICHT TUN**

Kein leeres `data/` erzeugen, keine Dateirechte pauschal auf `777`, keine Secrets in Logs ausgeben.

**ESKALIEREN WENN**

Container nach einem kontrollierten Neustart erneut unhealthy ist oder DB-/Secretursache nicht eindeutig feststeht.

## Caddy ausgefallen

**SYMPTOM**

Ports 80/443 antworten nicht oder 502, während Allocator intern gesund sein kann.

**Wahrscheinliche Ursachen**

Caddy-Container gestoppt, ungültige Caddyfile, Portkonflikt, Zertifikats-/Netzwerkproblem.

**PRÜFEN**

```bash
cd /opt/anny_webhook
docker compose ps caddy allocator
docker compose logs --since=30m --tail=300 caddy
docker compose exec -T caddy caddy validate --config /etc/caddy/Caddyfile
ss -lntp | grep -E ':(80|443)[[:space:]]'
```

**MASSNAHME**

Ungültige Caddy-Änderung auf letzte geprüfte Version zurücksetzen. Bei gestopptem, ansonsten gültigem Container `docker compose up -d --no-deps caddy` ausführen und TLS/Health prüfen.

**NICHT TUN**

TLS nicht durch öffentlichen HTTP-Betrieb umgehen; keine neue Proxysoftware parallel auf 80/443 starten.

**ESKALIEREN WENN**

Portkonflikt, wiederholter Exit oder Zertifikatsproblem nach validierter Konfiguration bestehen bleibt.

## Anny-Buchung erhält keinen Tisch

**SYMPTOM**

In Anny/Bestätigung fehlt „Deine Tische“ oder eine manuelle Warnung erscheint.

**Wahrscheinliche Ursachen**

Webhook fehlt, Buchung gehört nicht zur Ressource 181227, echte Kapazität reicht nicht, Anny-/SQLite-Kapazitätsmodell weicht ab, API/PATCH schlug fehl, ungültiger Zeitraum oder Stornozustand.

**PRÜFEN**

1. Buchungs-ID/-nummer, Ressource, Service, Status, Zeitraum und `weight` in Anny prüfen.
2. Anny Call History für create/update ansehen.
3. Dashboard „unassigned“/Webhookfehler prüfen.
4. Gezielt in SQLite read-only suchen:

```bash
cd /opt/anny_webhook
docker compose exec -T allocator python - '<BOOKING_NUMBER>' <<'PY'
import sqlite3
import sys

connection = sqlite3.connect('file:/data/allocator.db?mode=ro', uri=True)
row = connection.execute(
    'SELECT booking_id, booking_number, resource_id, start_date, end_date, need, tables_csv, status, updated_at FROM allocations WHERE booking_number=?',
    (sys.argv[1],),
).fetchone()
print(row)
connection.close()
PY
```

**MASSNAHME**

Bei `NOT_ENOUGH_FREE_TABLES` Kapazität/Blocker in Anny prüfen; nach Storno muss create/update/delete zugestellt worden sein. Bei retry-fähigem Fehler Ursache beheben und genau das Ereignis kontrolliert erneut senden. Bei Scope/Ressource Anny-Konfiguration korrigieren.

**NICHT TUN**

Keine Tischlabels direkt in SQLite eintragen. Keine mehrfachen blinden Webhook-Replays.

**ESKALIEREN WENN**

Physisch freie Kapazität besteht, aber Reconciliation nicht zuweist; Patch in Anny und SQLite divergieren; Gasttermin bevorsteht.

## Webhook kommt nicht an

**SYMPTOM**

Keine aktuelle Anny Call-History-Zustellung und kein neues `webhook_events`-Ereignis.

**Wahrscheinliche Ursachen**

Webhook inaktiv, falsche Events/Ressourcenbeschränkung/URL, Anny-Störung, DNS/Health nicht erreichbar.

**PRÜFEN**

- Anny API → Webhook `webhook_anny`: aktiv, URL auf Produktionsdomain, Events create/update/delete, Ressource 181227.
- Call History inklusive Fehlerzähler prüfen.
- öffentliche Domain und `/health` prüfen.
- letzte Eventzeit im Dashboard vergleichen.

**MASSNAHME**

Fehlende Konfiguration nach [07_ANNY_CONFIGURATION.md](07_ANNY_CONFIGURATION.md) korrigieren. Nach Wiederherstellung genau eine gekennzeichnete Testbuchung auslösen.

**NICHT TUN**

Keinen ungeschützten zweiten Webhook anlegen, Secret nicht aus URL kopieren, keine Massenzustellung aus der gesamten History.

**ESKALIEREN WENN**

Anny keine Zustellversuche erzeugt oder fünf aufeinanderfolgende Fehler eine automatische Deaktivierung riskieren.

## Anny API nicht erreichbar

**SYMPTOM**

Webhook liefert HTTP 503/retry-fähige Anny-GET-/PATCH-Fehler; Dashboard zeigt Fehler.

**Wahrscheinliche Ursachen**

Anny-/Cloudflare-Störung, DNS/Netzwerk vom Droplet, Timeout oder Tokenproblem.

**PRÜFEN**

- Anny Status/Bedienoberfläche und Call History prüfen.
- Server-DNS und HTTPS-Verbindung zu `b.anny.co` testen, ohne Authorization-Header auszugeben.
- Caddy/Allocator-Logs nur nach Status/Timeout durchsuchen.

```bash
getent hosts b.anny.co
curl --head --max-time 15 https://b.anny.co/
```

**MASSNAHME**

Bei externer Störung keine lokale Datenmanipulation; Anny-Retries beobachten. Nach Wiederherstellung retry-fähige Ereignisse und offene Buchungen kontrolliert abgleichen.

**NICHT TUN**

Token nicht in `curl`-Kommandozeile oder Ticket setzen; 503 nicht künstlich auf 200 umbiegen.

**ESKALIEREN WENN**

Störung länger als Anny-Retryfenster dauert oder bevorstehende Buchungen betroffen sind.

## API Token ungültig

**SYMPTOM**

Anny API antwortet 401/403; alle GET/PATCH-Vorgänge scheitern.

**Wahrscheinliche Ursachen**

Token abgelaufen/widerrufen, falscher Wert in `.env`, fehlende Scopes oder falsche Organisation.

**PRÜFEN**

- In Anny Tokenname, Ablauf und Scopes prüfen, niemals Wert anzeigen/kopieren.
- Auf Server nur Vorhandensein des Env-Schlüssels prüfen, nicht den Inhalt.
- Letzte Credential-Rotation und Containerneustart prüfen.

**MASSNAHME**

Neuen Token mit ausschließlich `b.bookings:read` und `b.bookings:update` erzeugen, im Secret-Manager und `.env` austauschen, Allocator neu erstellen, kontrolliert GET/PATCH testen, danach alten Token widerrufen. Details: [10_SECURITY_AND_SECRETS.md](10_SECURITY_AND_SECRETS.md#anny-api-token).

**NICHT TUN**

Keinen überberechtigten Alt-Token als Dauerlösung reaktivieren, Token nicht chatten oder loggen.

**ESKALIEREN WENN**

Kein unabhängiger Anny-Admin verfügbar ist oder neuer Minimal-Token weiterhin 403 liefert.

## SQLite locked

**SYMPTOM**

`database is locked`, Webhooktimeouts oder 503; Health kann je nach Zeitpunkt noch grün sein.

**Wahrscheinliche Ursachen**

zweiter Allocator/Worker, lang laufender externer DB-Zugriff, Backup-/Diagnoseprozess mit Schreibtransaktion oder I/O-Problem.

**PRÜFEN**

```bash
cd /opt/anny_webhook
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
docker inspect --format '{{.Config.Cmd}}' anny_webhook-allocator-1
lsof /opt/anny_webhook/data/allocator.db /opt/anny_webhook/data/allocator.db-wal /opt/anny_webhook/data/allocator.db-shm 2>/dev/null
docker compose logs --since=30m allocator | tail -200
```

**MASSNAHME**

Unbeabsichtigten zweiten Writer identifizieren und kontrolliert stoppen. Externe Schreibsession beenden. Danach Health und betroffene retry-fähige Ereignisse prüfen. Ein einzelner kontrollierter Allocator-Neustart ist erst nach Ursachenklärung zulässig.

**NICHT TUN**

`-wal`/`-shm` nicht löschen, Rechte nicht auf `777`, keinen zweiten Worker starten.

**ESKALIEREN WENN**

Lock nach 30-Sekunden-Busy-Timeout wiederkehrt oder kein zweiter Writer identifizierbar ist.

## SQLite beschädigt

**SYMPTOM**

`database disk image is malformed`, `integrity_check` nicht `ok`, Container startet nicht oder Dashboarddaten sind unlesbar.

**Wahrscheinliche Ursachen**

Disk-/Dateisystemproblem, abgebrochene unsichere Kopie/Restore, Hardware-/Hostfehler.

**PRÜFEN**

```bash
cd /opt/anny_webhook
docker compose exec -T allocator python -c "import sqlite3; c=sqlite3.connect('file:/data/allocator.db?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()"
dmesg --level=err,warn | tail -100
df -h /
```

Wenn Container nicht läuft, dieselbe Read-only-Prüfung mit Host-Python auf dem absoluten Pfad ausführen.

**MASSNAHME**

Allocator stoppen, DB/WAL/SHM recoverable quarantänisieren und letztes geprüftes Backup gemäß [Restore](05_BACKUP_AND_RESTORE.md#restore-szenario-1-sqlite-problem) installieren. Ereignislücke mit Anny abgleichen.

**NICHT TUN**

Kein Löschen der Originaldateien, kein ungetestetes `.recover` direkt über Produktion, keine leere DB akzeptieren.

**ESKALIEREN WENN**

Kein verifiziertes Backup vorhanden ist oder Disk-/Kernel-Fehler auf Hostproblem hindeuten.

## Festplatte voll

**SYMPTOM**

`No space left on device`, DB-/Containerfehler, Zertifikat-/Logprobleme.

**Wahrscheinliche Ursachen**

Docker-Images/Buildcache, Backups, Systemlogs oder andere Dateien; Containerlogs sind begrenzt, aber Image-/Backup-Retention derzeit nicht formalisiert.

**PRÜFEN**

```bash
df -h /
df -ih /
docker system df
du -x -h --max-depth=1 /opt /var/lib/docker /var/log 2>/dev/null | sort -h
find /opt/anny_webhook/backups -maxdepth 2 -type f -printf '%s %TY-%Tm-%Td %p\n' | sort -n | tail -30
```

**MASSNAHME**

Ursache identifizieren. Alte Artefakte erst offsite sichern und nach dokumentierter Retention gezielt entfernen. Bei akutem Risiko Droplet-Disk kontrolliert vergrößern und Dateisystem nach Provideranleitung erweitern.

**NICHT TUN**

Kein blindes `docker system prune -a`, keine Backups/DB/Logs ohne Incident-Sicherung löschen.

**ESKALIEREN WENN**

Unter 10 % frei, Schreibfehler bereits aufgetreten oder nicht eindeutig klar ist, welche Images/Backups benötigt werden.

## Server nicht erreichbar

**SYMPTOM**

HTTPS und SSH timeouten; möglicherweise IP nicht pingbar.

**Wahrscheinliche Ursachen**

Droplet aus/gelöscht, Providerstörung, Netzwerk-/Firewalländerung, Kernel-/Diskproblem.

**PRÜFEN**

- DNS-A-Record gegen bekannte IP prüfen.
- DigitalOcean Control Panel: Dropletstatus, Konsole, Events, Netzwerk und Billing prüfen.
- Providerstatus über unabhängige Verbindung prüfen.
- `ssh -vv <ADMIN_USER>@138.68.87.128` nur lokal auswerten; keine privaten Schlüssel teilen.

**MASSNAHME**

Bei laufendem Droplet Providerkonsole nutzen und Netzwerk/Services diagnostizieren. Bei Verlust [Disaster Recovery](12_DISASTER_RECOVERY.md) starten.

**NICHT TUN**

Keinen neuen Droplet mit gleicher Domain umschalten, bevor DB/Secrets/Release geprüft sind; alten Droplet nicht löschen.

**ESKALIEREN WENN**

Immer an DigitalOcean-Owner/Billingkontakt; nach fünf Minuten an Business Owner wegen Buchungsbetrieb.

## Domain/DNS funktioniert nicht

**SYMPTOM**

Domain löst nicht auf, zeigt auf falsche IP oder nur direkte IP ist erreichbar.

**Wahrscheinliche Ursachen**

A-Record/Zone/Nameserver geändert, Domain abgelaufen, DNSSEC-/Providerproblem, Cache während geplanter Umstellung.

**PRÜFEN**

```bash
dig +short webhook.voltabreau.ch A
dig webhook.voltabreau.ch A +trace
dig voltabreau.ch NS +short
curl --resolve webhook.voltabreau.ch:443:138.68.87.128 https://webhook.voltabreau.ch/health
```

Soll: A `138.68.87.128`, Nameserver Hosttech. Kein AAAA war beim Audit gesetzt.

**MASSNAHME**

Im autorisierten DNS-Konto letzte Änderung/Domainstatus prüfen und auf den verifizierten Zielserver korrigieren. TTL und Propagation berücksichtigen.

**NICHT TUN**

Keinen zusätzlichen widersprüchlichen A/AAAA-Record setzen; Domain nicht durch IP in der Anny-Webhook-URL ersetzen, weil TLS/Hostnamenprüfung scheitert.

**ESKALIEREN WENN**

Account/Registrar-Ownership fehlt, Domain abgelaufen ist oder autoritative Nameserver falsche Daten liefern.

## HTTPS/TLS funktioniert nicht

**SYMPTOM**

Zertifikatswarnung, abgelaufenes/falsches Zertifikat, TLS-Handshakefehler.

**Wahrscheinliche Ursachen**

DNS zeigt falsch, Ports 80/443 blockiert, Caddy/Zertifikatsspeicherproblem, Systemzeit falsch, Rate Limit.

**PRÜFEN**

```bash
echo | openssl s_client -connect webhook.voltabreau.ch:443 -servername webhook.voltabreau.ch 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
timedatectl
cd /opt/anny_webhook
docker compose logs --since=24h caddy
ufw status numbered
```

**MASSNAHME**

DNS, Zeit und Ports korrigieren; Caddy mit gültiger Konfiguration weiterlaufen lassen, damit automatische Erneuerung erfolgt. Caddy-Datenvolume nicht ersetzen, solange Ursache ungeklärt ist.

**NICHT TUN**

Zertifikatsprüfung nicht deaktivieren, kein selbstsigniertes Produktionszertifikat als Dauerlösung, nicht wiederholt Zertifikate anfordern.

**ESKALIEREN WENN**

Zertifikat weniger als 14 Tage gültig ist und keine Erneuerung sichtbar wird oder ACME-/Rate-Limitfehler auftreten.

## Container startet ständig neu

**SYMPTOM**

`RestartCount` steigt, Health bleibt starting/unhealthy, Logs wiederholen denselben Startfehler.

**Wahrscheinliche Ursachen**

fehlende Env-Variable, Syntax-/Importfehler, falsches Image, DB-/Mount-/Rechteproblem oder Speichermangel.

**PRÜFEN**

```bash
cd /opt/anny_webhook
docker inspect --format 'exit={{.State.ExitCode}} error={{.State.Error}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}' anny_webhook-allocator-1
docker compose logs --tail=300 allocator
docker inspect --format '{{json .Mounts}}' anny_webhook-allocator-1
free -h
```

**MASSNAHME**

Bei neuem Release sofort auf verifiziertes Image zurückrollen. Bei OOM Ressourcennutzung/Servergröße prüfen. Bei Env/DB nur die klar identifizierte Ursache beheben.

**NICHT TUN**

Restart-Policy nicht als „Fix“ entfernen, keine unbekannten Env-Werte einsetzen, nicht immer wieder manuell starten.

**ESKALIEREN WENN**

Ursache nach Log-/Mount-/Exitcode-Prüfung unklar oder DB beteiligt ist.

## Doppelbelegung erkannt

**SYMPTOM**

Zwei überschneidende `assigned`-Buchungen derselben Ressource enthalten dasselbe Tischlabel; Dashboard Rot.

**Wahrscheinliche Ursachen**

Siehe „Dashboard Rot“, insbesondere Parallelinstanz, Restore oder manuelle Datenänderung.

**PRÜFEN**

Kollisionspaar und Zeitfenster im Dashboard sichern; in Anny beide aktuellen Buchungszustände und Notizen prüfen; Anzahl Allocator-Prozesse/Container prüfen.

**MASSNAHME**

Operativen Betrieb für das Zeitfenster absichern, eindeutige manuelle Tischentscheidung durch zuständige Person treffen, technischen Writer auf eine Instanz begrenzen, Ursache beheben und erst dann kontrolliert neu zuweisen/patchen.

**NICHT TUN**

Keine automatische Stornierung oder zufällige DB-Korrektur; Konflikt nicht nur in einer Anny-Notiz kaschieren.

**ESKALIEREN WENN**

Immer sofort an Technical Owner und Betriebsverantwortlichen; bei mehreren Zeitfenstern Release rollbacken.

## Deployment fehlgeschlagen

**SYMPTOM**

Build/Start/Health/Dashboard/Anny-Test scheitert oder neue Fehler/Kollisionen erscheinen.

**Wahrscheinliche Ursachen**

falscher Commit, Build-/Dependencyfehler, fehlende Datei/Env, falsches Mount, inkompatible Änderung oder Caddyfehler.

**PRÜFEN**

- Release-SHA gegen OCI-Label prüfen.
- Compose-/Containerstatus, Mounts, Logs und Health prüfen.
- Prüfen, ob `.env` und `data/` unverändert sind.
- Pre-Deployment-Backup und Rollback-Image verifizieren.

**MASSNAHME**

Deployment stoppen und [Rollback](04_DEPLOYMENT.md#rollback) ausführen. DB nur bei nachgewiesener Notwendigkeit wiederherstellen.

**NICHT TUN**

Nicht direkt auf dem Server weiterpatchen, kein zweites Image parallel produktiv starten, DB nicht pauschal zurücksetzen.

**ESKALIEREN WENN**

Rollback-Image/Backup fehlt, Health nach Rollback nicht zurückkehrt oder reale Buchungen im Änderungsfenster betroffen sind.

## Incident-Abschluss

Ein Incident ist erst abgeschlossen, wenn:

- `/health`, Docker Health und Dashboard geprüft sind,
- eine kontrollierte Anny-Zustellung erfolgreich war,
- keine neue Kollision besteht,
- betroffene Buchungen abgeglichen wurden,
- Backup nach der Reparatur erfolgreich und offsite ist,
- Ursache, Maßnahmen, Datenlücke und Follow-ups ohne Secrets dokumentiert sind.
