# 11 – Maintenance

Stand: 1. September 2026

## Verantwortlichkeit

Jede Routine braucht einen Primärverantwortlichen, eine Vertretung und einen dokumentierten Ablageort für das Ergebnis. Bis diese Personen festgelegt sind, lauten sie:

`xxx – organisatorisch festlegen`

Routineprüfungen dürfen keine Secrets oder Kundendaten in Tickets kopieren.

## Wöchentlich

- `/health` und Dashboard prüfen; konkrete Ursache jeder gelben/roten Anzeige erfassen.
- Anny Call History auf wiederholte Fehler, inaktiven Webhook oder unerwartete Eventtypen prüfen.
- zukünftige `unassigned`-Buchungen und Kollisionen prüfen.
- Docker-Health und RestartCount prüfen.
- Root-Disk und Inodes prüfen; bei <20 % frei Maßnahmen planen.
- Alter, Hash, `PRAGMA integrity_check` und Offsite-Status des letzten automatischen Backups prüfen.
- offene Security-/Dependabot-/Secret-Scanning-Alerts in GitHub sichten.

Sichere Befehle:

```bash
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
cd /opt/anny_webhook
docker compose ps
docker inspect --format 'health={{if .State.Health}}{{.State.Health.Status}}{{end}} restarts={{.RestartCount}}' anny_webhook-allocator-1
df -h /
df -ih /
```

## Monatlich

- eine zufällig ausgewählte Offsite-Sicherung herunterladen, Hash und SQLite-Integrität in isolierter Umgebung prüfen.
- Ubuntu-/Docker-/Caddy-/Python-Sicherheitsupdates und nötigen Reboot bewerten; nicht unkontrolliert während Buchungsbetrieb aktualisieren.
- TLS-Laufzeit und Caddy-Erneuerungslogs prüfen.
- Ablaufdaten von Anny-Token, Domain und Provider-/Zahlungsverträgen prüfen.
- Docker-Images, Release-Verzeichnisse und lokale Backups gegen dokumentierte Retention prüfen; nichts blind prunen.
- Monitoring-Testalarm auslösen und Empfang bei Primär/Vertretung bestätigen.
- Benutzer-/Adminlisten in GitHub, DigitalOcean, Anny, DNS, Backup und Monitoring auf unerwartete Zugriffe prüfen.
- Stichprobe einer realen, datensparsam dokumentierten Buchungs-/Stornoverarbeitung durchführen.

## Quartalsweise

- vollständigen Restore der SQLite-Sicherung in einer isolierten, nicht schreibend mit Anny verbundenen Umgebung durchführen.
- Disaster-Recovery-Schritte bis zum Start einer isolierten Ersatzinstanz proben und Zeit messen.
- RTO/RPO anhand der Messung und betrieblichen Anforderungen bestätigen.
- alle SSH-Key-Fingerprints, MFA-/Recoverywege und Break-glass-Zugriffe mit Owner abgleichen.
- Service-/Weight-/Kapazitätsinventar in Anny mit dem tatsächlichen Angebot abstimmen.
- Incidentkontakte, Billing, Domainverlängerung und Vertretungen bestätigen.
- Dependency-/Base-Image-Updates in separatem Branch testen und ein geplantes Release vorbereiten.
- Aufbewahrung/Datenschutz von Logs, DB-Backups und quarantänisierten Incidentdateien prüfen.

## Bei jeder neuen Version

- exakte Release-SHA reviewen; sauberen Checkout verwenden.
- vollständige Tests, Python-Kompilierung und Compose-Validierung ausführen.
- Änderungen an Schema, Secrets, Compose, Caddy und Anny-Konfiguration gesondert bewerten.
- konsistentes DB-Backup erzeugen, Integrität prüfen und offsite replizieren.
- aktuelles Image, Code und referenzierte Secret-/Konfigurationsversion als Rollbackstand sichern.
- nur einen Allocator-Writer betreiben.
- Health, Logs, Dashboard-Auth und Kollisionen prüfen.
- kontrollierte Anny-Testbuchung plus Storno durchführen.
- bei Logik-/Kapazitätsänderungen Vollbelegungs-/Warteschlangen-/Nachverteilungstest durchführen.
- Release-SHA, Image-ID, Backup-Hash, Prüfer und Ergebnis protokollieren.

Verbindlicher Ablauf: [04_DEPLOYMENT.md](04_DEPLOYMENT.md).

## Bei Personalwechsel

- Ownership-Matrix und Eskalationskontakte aktualisieren.
- neue namentliche Accounts/SSH-Keys/MFA zuerst einrichten und testen.
- persönliche Zugriffe der ausscheidenden Person entfernen.
- alle bekannten beziehungsweise zugänglichen Secrets rotieren.
- Dashboard-Credential rotieren oder Benutzer entfernen.
- GitHub-/Provider-/DNS-/Anny-/Backup-/Monitoring-Adminlisten prüfen.
- Billing-/Recovery-Mails und Recovery-Codes aktualisieren.
- Backupzugriff, Testalarm, Deployment, Rollback und Restore durch Nachfolger abnehmen.
- vollständige Offboarding-Checkliste in [10_SECURITY_AND_SECRETS.md](10_SECURITY_AND_SECRETS.md#wenn-philipp-das-unternehmen-verlässt) verwenden.

## Nach Infrastruktur- oder Anny-Änderung

- DNS/Caddy/Firewall: externe Domain, TLS und `/health` prüfen.
- Token/Secret: Container neu erstellen und End-to-End-Test durchführen.
- Services/Weights/Kapazität: Testfälle für 1 bis 8 Tische sowie Mischbelegung prüfen.
- Servergröße/Disk: OOM, freien Speicher und Backupzeit kontrollieren.
- Docker-/Uvicorn-Skalierung: keine zweite Instanz/Worker ohne neue verteilte Sperrarchitektur.

## Wartungsprotokoll

Minimal erfassen:

```text
Datum/Zeit (UTC und Europe/Zurich):
Ausgeführt von:
Prüfung/Änderung:
Git-SHA/Image-ID:
Backup-Datei und SHA-256:
Ergebnis:
Abweichung/Incident:
Follow-up, Owner, Termin:
```

Keine Secretwerte, vollständigen Payloads oder Kundendaten eintragen.

## Derzeit offene Wartungsvoraussetzungen

- **HANDOVER BLOCKER:** automatischer Offsite-Backupjob und Erfolgsalarm fehlen/nicht verifiziert
- **HANDOVER BLOCKER:** Routine-Owner und Vertretung fehlen
- **HIGH PRIORITY:** externer Monitoring-/Testalarm fehlt/nicht verifiziert
- **HIGH PRIORITY:** Alt-Token, SSH-Härtung und persönliches Dashboardkonto
- **RECOMMENDED:** CI/Dependency-Automation und dokumentierte Retention
