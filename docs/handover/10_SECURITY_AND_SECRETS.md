# 10 – Security and Secrets

Stand: 1. September 2026

## Sicherheitsziel

Volta Bräu kontrolliert Accounts, MFA, Recovery, Secrets, Schlüssel und Backups. Produktion läuft mit minimalen Rechten, und der Austritt einer Person lässt keinen unbekannten Zugriff oder betrieblichen Single Point of Failure zurück.

## Aktueller Sicherheitsstand

### Verifiziert vorhanden

- Produktions-`.env` mit Dateimodus `0600`
- keine `.env`, DB, privaten Keys oder Backups als getrackte Repository-Dateien
- `.gitignore` schließt Secrets, SQLite, Keys und Logs aus
- GitHub Secret Scanning und Push Protection aktiv; beim Audit keine offenen Secret-Scanning-Alerts
- minimal berechtigter produktiver Anny-Token (`b.bookings:read`, `b.bookings:update`)
- Dashboard und `/allocations` fail-closed per Basic Auth
- HTTPS über Caddy
- UFW mit 22/80/443; Port 8099 nur intern
- Allocator read-only, tmpfs `/tmp`, `no-new-privileges`
- begrenzte Docker-JSON-Logs
- Uvicorn ohne Access-Log, damit Query-Secret nicht protokolliert wird
- automatische Ubuntu-Sicherheitsupdates aktiviert

### Offene Risiken

- persönliches GitHub-Repository, nur ein verifizierter Admin
- Root- und Passwortlogin per SSH aktiv
- Zuordnung/Owner der vorhandenen SSH-Keys ungeklärt
- alter, überberechtigter Anny-Token aktiv
- gemeinsames Dashboard-Passwort ohne Rollen, MFA oder Resetflow; Benutzername personengebunden
- Webhook-Secret in Query-URL statt nur in Header/Signatur
- organisatorischer Secret-Manager, MFA/Recovery und Offsite-Backup nicht verifiziert
- GitHub-`main` beim Audit ohne Branch Protection, 0 Actions-Workflows; Dependabot Security Updates deaktiviert

## Secret-Inventar

| Secret | Zweck | Laufzeitort | Erzeugung | Rotation | Danach neu starten/ändern |
| --- | --- | --- | --- | --- | --- |
| `ANNY_TOKEN` | GET/PATCH von Buchungen | `.env` → Allocator-Environment | Anny API mit minimalen Scopes | neuen Token parallel testen, alten danach widerrufen | Allocator neu erstellen |
| `WEBHOOK_SECRET` | Authentifiziert POST `/` | `.env` und Anny-Webhook-URL | starker Zufallswert | geplantes kurzes Fenster; Server und Anny koordinieren | Allocator neu erstellen, Anny URL ändern |
| `DASHBOARD_PASSWORD` | Basic Auth | `.env` → Allocator | eigenständiger langer Zufallswert | bei Austritt/Leak und nach Policy | Allocator neu erstellen; Benutzer informieren |
| SSH Private Key | Serverzugang | nur Gerät/geschützter Key Store des Admins | pro Person neu erzeugen | neuen Key testen, alten Public Key entfernen | kein Containerrestart; SSH-Verbindung testen |
| DigitalOcean Recovery | Providerkontrolle | Provider/organisatorischer Vault | Providerprozess | Personal-/Recoverywechsel | kein Apprestart |
| Domain/DNS Recovery | Domainkontrolle | Registrar/DNS/organisatorischer Vault | Providerprozess | Personal-/Recoverywechsel | kein Apprestart, außer DNS-Änderung |
| GitHub Recovery/Tokens | Repositorykontrolle | GitHub/organisatorischer Vault | GitHub | Personalwechsel/Leak | ggf. CI neu autorisieren |
| Backup Encryption Key | Offsite-Backup entschlüsseln | organisatorischer Vault plus Break-glass | noch festzulegen | mit überprüfter Re-Encryption | Backupjob/Restoretest aktualisieren |

Keine echten Werte gehören in diese Tabelle oder in Git.

## `.env`

- Produktionspfad: `/opt/anny_webhook/.env`
- Sollrechte: `0600`, Owner nur technischer Betriebsaccount/root
- Werte nie mit `cat`, `env`, ungezieltem `docker inspect` oder Supportdump ausgeben
- keine Kopie in Release-Verzeichnisse oder unverschlüsselte Backups
- Ziel: Werte einzeln im organisatorischen Secret-Manager; `.env` nur Deploymentkopie

Nur Namen und Konfigurationsstatus prüfen:

```bash
cd /opt/anny_webhook
stat -c '%a %U:%G %n' .env
sed -E '/^[[:space:]]*(#|$)/d; s/=.*$/=<configured>/' .env
```

Der zweite Befehl zeigt keine Werte, setzt aber voraus, dass keine ungewöhnliche mehrzeilige Env-Syntax verwendet wird.

## Credential Rotation

### Anny API Token

Vollständiger Ablauf: [07_ANNY_CONFIGURATION.md](07_ANNY_CONFIGURATION.md#api-token-rotieren).

Wichtig: `docker compose restart allocator` liest eine geänderte `env_file` nicht neu ein. Verwenden:

```bash
docker compose up -d --no-build --no-deps --force-recreate allocator
```

### Webhook-Secret

Vollständiger Ablauf: [07_ANNY_CONFIGURATION.md](07_ANNY_CONFIGURATION.md#webhook-secret-rotieren). Aktuell existiert kein Dual-Secret-Mechanismus. Rotation braucht ein kontrolliertes Fenster und unmittelbaren End-to-End-Test.

### Dashboard-Zugang

1. neuen organisatorischen Benutzernamen und langes, einzigartiges Passwort erzeugen,
2. beides im Secret-Manager versionieren,
3. `.env` sicher aktualisieren,
4. Allocator neu erstellen,
5. ohne Auth HTTP 401 und mit neuem Zugang Dashboard HTTP 200 prüfen,
6. alte Zugangsdaten aus autorisierten Speichern entfernen,
7. Rotation ohne Werte protokollieren.

Das Dashboard ist read-only und kennt keine Super-Admin-Rolle. Der aktuelle einzelne Basic-Auth-Login darf nicht als vollwertige Benutzerverwaltung missverstanden werden.

## SSH Keys, Root und Passwortlogin

### Zielzustand

- mindestens zwei namentliche Wartungsbenutzer
- je Person eigener passwortgeschützter SSH-Key
- `PasswordAuthentication no`
- `PermitRootLogin no` nach getestetem sudo-/Break-glass-Verfahren
- Providerkonsole mit MFA und dokumentiertem Recovery
- Key-Fingerprint-Inventar mit Owner, Zweck, Hinzugefügt-/Entfernt-Datum

### Sichere Umstellungsreihenfolge

Diese Änderungen sind produktionsrelevant und benötigen separate Freigabe. Bestehende Root-Session während der Prüfung offen lassen.

1. Providerkonsole und Recovery mit einem zweiten Admin testen.
2. Namentlichen Benutzer anlegen und kontrollierte sudo-Rechte vergeben.
3. Vom Arbeitsplatz ausschließlich den **öffentlichen** persönlichen Key hinzufügen.
4. Zweite SSH-Session öffnen und Login plus `sudo -v` testen.
5. SSH-Konfiguration sichern, Drop-in ändern und mit `sshd -t` validieren.
6. Zuerst Passwortlogin deaktivieren; neue Verbindung testen.
7. Root-Login erst deaktivieren, wenn namentliche Admins und Break-glass funktionieren.
8. Philipps Public Key erst nach vollständigem Handover entfernen.

Beispielprüfung ohne Secretinhalt:

```bash
sshd -T | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries) '
ssh-keygen -lf /root/.ssh/authorized_keys
getent group sudo
```

`ssh-keygen -lf` auf einer Datei mit mehreren Keys kann je nach Format nur einen Teil abbilden; für die Übergabe jeden Key einzeln inventarisieren, ohne privaten Key anzufordern.

## Firewall und Netzwerk

- UFW: nur 22, 80, 443 öffentlich erforderlich
- 8099 bleibt Docker-intern
- DigitalOcean Cloud Firewall/VPC-Regeln sind noch zu verifizieren
- SSH nach Möglichkeit auf organisatorische Adminnetze/VPN begrenzen, erst nach getesteter Recovery
- neue IPv6-/AAAA-Freigabe nur zusammen mit Firewall-/App-Test

Keine Firewalländerung durchführen, bevor eine Providerkonsole als Recoveryweg bestätigt ist.

## Docker und Dateirechte

- Zugriff auf Docker-Socket ist faktisch Root-Recht; nur technische Admins erhalten ihn.
- keine parallelen Allocator-Instanzen/Worker
- Base Image und Python-Pakete regelmäßig auf Sicherheitsupdates prüfen
- Images mit Commit-SHA/OCI-Revision kennzeichnen
- `data/`, `.env`, Backups und Caddy-Daten nicht in allgemeine Supportarchive aufnehmen
- DB-/Backuprechte restriktiv halten (`0600`, Verzeichnisse `0700` soweit betrieblich möglich)
- keine Container mit `--privileged` oder Hostnetzwerk hinzufügen

## GitHub

Aktuell ist das Repository öffentlich unter persönlichem Owner `PhiluLan`. Quellcode und Dokumentation enthalten keine vorgesehenen Secrets; öffentlich bedeutet dennoch, dass jeder Commit dauerhaft als veröffentlicht betrachtet werden muss.

Zielzustand:

- Transfer in Volta-Bräu-GitHub-Organisation
- mindestens zwei Organization Owner
- Branch Protection für `main`, Review und erfolgreiche Tests
- CI für Tests/Secret-/Dependency-Scanning
- Dependabot/Sicherheitsupdates aktivieren und zuständigen Empfänger festlegen
- keine persönlichen PATs als alleinige Deploymentberechtigung
- Release-/Auditprotokoll pro Produktions-SHA

## Backups

- Backups enthalten Buchungsmetadaten und gegebenenfalls Secrets; verschlüsseln und Zugriff protokollieren.
- `.env` getrennt von DB und niemals unverschlüsselt offsite speichern.
- Backup-Encryption-Key darf nicht nur auf demselben Droplet oder Philipps Gerät liegen.
- Restore-Rechte auf wenige benannte Admins begrenzen.
- Löschung nach definierter Retention und Datenschutzanforderung, nicht ad hoc.

## Wenn ein Secret kompromittiert ist

1. Incident-Verantwortlichen benennen und Zeitpunkt/Umfang erfassen.
2. Neues Secret mit minimalen Rechten erzeugen.
3. Verbraucher kontrolliert umstellen und testen.
4. altes Secret widerrufen/deaktivieren.
5. Logs, Git-History, Chat/Tickets und Backups auf Exposition bewerten, ohne Wert erneut zu verbreiten.
6. betroffene Sessions/Tokens/Keys invalidieren.
7. Ursache beheben und Rotation dokumentieren.
8. Bei personenbezogenen Daten Datenschutzverantwortliche einbeziehen.

Ein in Git eingechecktes Secret wird durch späteres Löschen nicht wieder geheim.

## Wenn Philipp das Unternehmen verlässt

Die Reihenfolge verhindert Aussperrung und persönliche Restabhängigkeit.

- [ ] neuen Business Owner und Technical Owner namentlich festlegen
- [ ] Volta-Bräu-GitHub-Organisation beziehungsweise organisatorischen Owner mit zwei Admins einrichten
- [ ] Repository und Security Settings übertragen und Clone/Push testen
- [ ] zwei DigitalOcean-Teamadmins, MFA, Recovery und Billing testen
- [ ] neuen namentlichen SSH-Benutzer und eigenen SSH-Key hinzufügen
- [ ] Login, sudo, Dockerdiagnose und Providerkonsole testen
- [ ] Philipps SSH-Public-Key aus allen Benutzerkonten entfernen
- [ ] Root-/Passwortlogin gemäß getesteter Reihenfolge härten
- [ ] Philipps persönliche GitHub-Berechtigungen und Tokens entfernen/widerrufen
- [ ] Philipps persönliche DigitalOcean-Berechtigungen entfernen
- [ ] Domain-/DNS-Ownership, MFA, Recovery und Billing auf Volta Bräu übertragen
- [ ] Philipps persönliche Domain-/DNS-Berechtigungen entfernen
- [ ] Anny-Owner/Adminliste, MFA, Recovery und Billing prüfen
- [ ] Philipps Anny-Benutzer/Tokens nach Businessfreigabe entfernen
- [ ] Anny API Token rotieren und alten überberechtigten Token widerrufen
- [ ] Webhook-Secret rotieren und erfolgreichen Call prüfen
- [ ] Dashboard auf organisatorischen Benutzernamen umstellen und Passwort rotieren
- [ ] GitHub-/Provider-/Backup-/Monitoring-Credentials rotieren, auf die Philipp Zugriff hatte
- [ ] Recovery-Codes und Break-glass-Zugänge neu erzeugen beziehungsweise prüfen
- [ ] Backup-Encryption-Key/Offsite-Zugriff prüfen und gegebenenfalls rotieren
- [ ] Testalarm an neue Empfänger senden
- [ ] vollständigen Restore- und Handover Acceptance Test bestehen
- [ ] schriftlich bestätigen, dass kein produktiver privater Account, Rechner, Schlüssel oder Zahlungsmittel mehr benötigt wird

Kein persönlicher Zugriff wird entfernt, bevor sein organisatorischer Ersatz nachweislich funktioniert. Nach Abschluss darf aber auch kein „vorsorglicher“ undokumentierter Zugang bestehen bleiben.

## Security-Lücken nach Priorität

### HANDOVER BLOCKER

- organisatorisches Account-/MFA-/Recovery-Ownership nicht nachgewiesen
- kein verifizierter organisatorischer Secret-Manager/Break-glass
- kein verschlüsseltes Offsite-Backup mit unabhängiger Schlüsselkontrolle
- persönliches GitHub-Ownership und nur ein verifizierter Admin

### HIGH PRIORITY

- Root-/Passwort-SSH
- alter überberechtigter Anny-Token
- gemeinsames personengebundenes Dashboard-Credential
- Query-Secret und fehlender Dual-Secret-/Signaturmechanismus

### RECOMMENDED

- Branch Protection, CI, Dependency-Updates und zentrale Auditlogs
- persönliche Dashboard-Authentifizierung mit MFA/Identity Provider
