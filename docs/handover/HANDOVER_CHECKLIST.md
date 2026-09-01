# Technical Handover Checklist

Diese Checklist ist der verbindliche Abschluss der technischen Übergabe. Ein Punkt gilt nur als erledigt, wenn ein von Philipp unabhängiger Verantwortlicher ihn mit eigenem Zugang praktisch bestätigt und der Nachweis ohne Secrets abgelegt wurde.

## Übergabeangaben

```text
Business Owner: xxx
Technical Owner: xxx
Stellvertretung: xxx
Externer Eskalationskontakt: xxx
Nachweis-/Protokollablage: xxx
Geplantes Übergabedatum: xxx
```

## GitHub

- [ ] Repository in eine von Volta Bräu kontrollierte GitHub-Organisation übertragen
- [ ] mindestens zwei Organization Owner mit MFA und Recovery getestet
- [ ] Nachfolger kann mit eigenem Account klonen, Branch/PR erstellen und freigegeben pushen
- [ ] Branch Protection/Reviews/Tests für `main` eingerichtet
- [ ] Secret Scanning, Push Protection und Dependency-Alerts geprüft; Verantwortlicher benannt
- [ ] Produktions-SHA und Release-Protokoll im Repository auffindbar
- [ ] keine produktiven persönlichen GitHub-Tokens für Deployment erforderlich

## DigitalOcean

- [ ] Volta-Bräu-Teamowner und zweiter Admin namentlich festgelegt
- [ ] beide melden sich mit eigenem Account und MFA an
- [ ] Droplet `138.68.87.128`/`fra1` im richtigen Team identifiziert
- [ ] Recovery-Mail/-Codes und Supportzugang getestet
- [ ] Droplet-/Volume-/Backupstatus im Control Panel dokumentiert
- [ ] DigitalOcean Cloud Firewall/VPC geprüft

## Server

- [ ] Hostname, OS, CPU/RAM/Disk, Zeitzone und IP mit [03_PRODUCTION_SERVER.md](03_PRODUCTION_SERVER.md) abgeglichen
- [ ] `/opt/anny_webhook`, `.env`, `data/`, `backups/` und Releasepfade verstanden
- [ ] Container, Images, Mounts, Ports, Health und Restart-Policy geprüft
- [ ] SQLite-Pfad und Integritätsprüfung selbstständig gefunden/ausgeführt
- [ ] UFW, automatische Updates, systemd/cron/Agenten inventarisiert
- [ ] Server-Baseline und Abweichungen ohne Secrets im Übergabeprotokoll abgelegt

## SSH

- [ ] jeder technische Admin besitzt einen eigenen, passwortgeschützten SSH-Key
- [ ] namentliche Wartungsbenutzer und sudo-/Dockerverfahren getestet
- [ ] Providerkonsole als Break-glass-Zugang getestet
- [ ] alle `authorized_keys` mit Fingerprint, Owner, Zweck und Datum inventarisiert
- [ ] Passwortlogin deaktiviert
- [ ] Root-Login nach getesteter Alternative deaktiviert
- [ ] kein privater Schlüssel wurde zwischen Personen kopiert

## Domain

- [ ] rechtlicher Owner und Registrar von `voltabreau.ch` bestätigt
- [ ] mindestens zwei organisatorische Registraradmins mit MFA
- [ ] Ablaufdatum, Auto-Renewal, Zahlungsmittel und Recovery geprüft
- [ ] Schreibunterschied `voltabreau.ch`/`voltabraeu.ch` verstanden und dokumentiert
- [ ] Domaintransfer-/Recoveryverfahren durch Technical und Business Owner verstanden

## DNS

- [ ] DNS-Provider/Hosttech-Account und Admins bestätigt
- [ ] A-Record `webhook.voltabreau.ch` und autoritative Nameserver geprüft
- [ ] kein unbeabsichtigter AAAA-/CAA-/Konfliktrecord vorhanden
- [ ] DNS-Änderung und Rollback in sicherer Übung erklärt
- [ ] DNS-/TLS-Monitoring und Alarmempfänger getestet

## Anny

- [ ] Volta-Bräu-/Volta-Pong-Org-Owner und mindestens zwei Admins bestätigt
- [ ] MFA, Recovery und Billing getestet
- [ ] Ressource 181227, relevante Services, `weight` und Tischbedarf inventarisiert
- [ ] Webhook aktiv, URL/Events/Restriction und Call History geprüft
- [ ] Minimal-Token mit `b.bookings:read`/`b.bookings:update` identifiziert
- [ ] alter überberechtigter Token `annyAPI` widerrufen
- [ ] Token-Ablaufalarm und Owner eingerichtet
- [ ] bekannte Kapazitätsproblematik fachlich entschieden und getestet

## Secrets

- [ ] organisatorischer Secret-Manager und mindestens zwei Recoveryberechtigte eingerichtet
- [ ] `ANNY_TOKEN`, `WEBHOOK_SECRET`, Dashboard-Credential und Recoverymaterial dort vollständig vorhanden
- [ ] keine echten Werte in Git, Tickets, Handover-Dokumenten oder unverschlüsselten Backups
- [ ] Produktions-`.env` aus Organisationsquelle rekonstruierbar und Modus `0600`
- [ ] alle Secrets rotiert, auf die Philipp Zugriff hatte
- [ ] Rotation und Container-/Providerfolgeschritte vom Nachfolger erklärt/getestet

## Dashboard

- [ ] Dashboard über `https://webhook.voltabreau.ch/dashboard` erreichbar
- [ ] ohne Authentifizierung HTTP 401, mit freigegebenem Zugang erfolgreich
- [ ] Organisationsaccount statt personengebundener Benutzername eingerichtet
- [ ] Passwort sicher verteilt und Rotation getestet
- [ ] Grenzen von Grün/Gelb/Rot sowie `/health` verstanden
- [ ] Zielentscheidung für persönliche Logins/MFA dokumentiert

## Backup

- [ ] automatisches konsistentes SQLite-Backup mindestens täglich eingerichtet
- [ ] Backup vor jedem Deployment vorgeschrieben
- [ ] `PRAGMA integrity_check`, SHA-256 und Altersprüfung automatisiert
- [ ] verschlüsselte Offsite-Kopie in anderem Failure Domain vorhanden
- [ ] Retention und datenschutzkonforme Löschung festgelegt
- [ ] Backup-Encryption-Key unabhängig vom Droplet/Philipps Gerät verfügbar
- [ ] Alarm bei Fehler, Überalterung oder fehlender Offsite-Kopie getestet
- [ ] Provider-/Droplet-Backupstatus bewusst dokumentiert

## Restore

- [ ] Nachfolger stellt `allocator.db` aus Offsite-Backup isoliert wieder her
- [ ] Hash, Integrität, Tabellen und Anwendungssmoke-Test erfolgreich
- [ ] produktiver Restoreablauf inklusive Quarantäne von DB/WAL/SHM erklärt
- [ ] Ereignislücke/RPO und Anny-Abgleich verstanden
- [ ] quartalsweiser Restore-Test terminiert und Owner benannt

## Monitoring

- [ ] externer `/health`-Check aktiv
- [ ] Container unhealthy/RestartCount und Disk Space überwacht
- [ ] zukünftige `unassigned`, Kollisionen und retry-fähige Webhookfehler alarmiert
- [ ] Backup-Erfolg/-Alter/-Integrität alarmiert
- [ ] DNS/TLS und Token-/Domainablauf überwacht
- [ ] Primär-/Sekundärempfänger und Eskalationszeiten dokumentiert
- [ ] Testalarm bei beiden Empfängern eingegangen

## Deployment

- [ ] Nachfolger kann Release-SHA auswählen und sauberen Checkout belegen
- [ ] 32+ Tests, Python-Kompilierung und Compose-Validierung erfolgreich
- [ ] Staging/Image mit OCI-Revision reproduzierbar gebaut
- [ ] Backup und Rollback-Image vor Umschalten erstellt
- [ ] Health, Logs, Dashboard, Anny-Buchung und Storno nach Deployment geprüft
- [ ] Release-Protokoll ohne Secrets vollständig
- [ ] entschieden, ob/wo CI/CD und Image Registry eingeführt werden

## Rollback

- [ ] vorheriges Image/Code/Compose eindeutig identifizierbar
- [ ] Anwendungsrollback ohne unnötigen DB-Restore in sicherer Umgebung getestet
- [ ] Entscheidungskriterien für DB-Restore verstanden
- [ ] Health/Dashboard/Anny-Abnahme nach Rollback durchgeführt
- [ ] Rollback-Zeit gemessen und akzeptiert

## Incident Response

- [ ] Primär-/Sekundärkontakt und Business-Eskalation benannt
- [ ] Zugriff auf [06_INCIDENT_RUNBOOK.md](06_INCIDENT_RUNBOOK.md) ohne Philipp möglich
- [ ] Tabletop für Ausfall, Tokenfehler, SQLite locked/corrupt und Kollision durchgeführt
- [ ] Datenschutz-/Security-Eskalation für Secret-/Kundendatenincident geklärt
- [ ] Incident-Protokollablage und Kommunikationskanal festgelegt

## Billing

- [ ] DigitalOcean-Zahlungsmittel, Rechnungsempfänger und Ausfallalarm organisatorisch
- [ ] Domainverlängerung und Rechnungsempfänger organisatorisch
- [ ] Anny-Vertrag/Billing organisatorisch
- [ ] Backup-/Monitoring-/GitHub-Kosten und Owner dokumentiert
- [ ] keine private Zahlart, Recovery-Mail oder Einzelperson ist für Fortbestand erforderlich

## Recovery

- [ ] neues Droplet mit eigenem Adminzugang in isolierter Übung erstellt
- [ ] Repository, Docker, Konfiguration, Secrets und SQLite unabhängig wiederhergestellt
- [ ] Caddy, DNS, TLS, `/health`, Dashboard und Anny-Test erfolgreich
- [ ] Ereignislücke seit Backup kontrolliert abgeglichen
- [ ] RTO/RPO gemessen, dokumentiert und vom Business Owner akzeptiert
- [ ] neuer Offsite-Backup- und Monitoringlauf nach Recovery erfolgreich

## Offboarding Philipp

- [ ] Nachfolger und Stellvertretung haben alle Zielzugänge erfolgreich getestet
- [ ] Philipps SSH-Public-Keys von allen Serveraccounts entfernt
- [ ] persönliche GitHub-Rechte/Tokens entfernt
- [ ] persönliche DigitalOcean-Rechte/Recoverydaten entfernt
- [ ] persönliche Domain-/DNS-Rechte/Recoverydaten entfernt
- [ ] persönlicher Anny-Zugang/Tokens nach Businessfreigabe entfernt
- [ ] Dashboard-Zugang rotiert
- [ ] alle weiteren bekannten Secrets mit Philipps Zugriff rotiert
- [ ] persönliche Geräte enthalten keine einzige notwendige Recovery-/Backupkopie
- [ ] schriftlich bestätigt: Betrieb, Billing und Recovery funktionieren ohne Philipp

## Handover Acceptance Test

Der Nachfolger führt unter Beobachtung, aber ohne aktive Hilfe von Philipp, mindestens Folgendes aus. Zu jedem Punkt werden Datum, Ergebnis und Nachweislink eingetragen.

- [ ] 1. GitHub-Repository finden und Aufbau/Quellen der Wahrheit erklären
- [ ] 2. Produktionsserver, Provider, IP, Domain und Produktions-SHA identifizieren
- [ ] 3. eigenen namentlichen SSH-Zugang verwenden
- [ ] 4. laufende Container, Images, Mounts und Health prüfen
- [ ] 5. Allocator-/Caddy-/Docker-Logs finden und secretsicher behandeln
- [ ] 6. `/health` extern und intern prüfen und Grenzen erklären
- [ ] 7. Dashboard öffnen, Auth und Grün/Gelb/Rot erklären
- [ ] 8. eine gekennzeichnete Testbuchung von Anny-Webhook über SQLite bis zum Rückschreiben verfolgen
- [ ] 9. konsistentes SQLite-Backup erstellen, Integrität/Hash prüfen und offsite bestätigen
- [ ] 10. Deployment vollständig erklären und in sicherer Umgebung oder genehmigtem Release durchführen
- [ ] 11. Rollback erklären und in sicherer Umgebung testen
- [ ] 12. Restore einer DB-Kopie erklären und praktisch testen
- [ ] 13. Anny-Webhook, Events, Ressource, Call History und Fehlerzähler finden/prüfen
- [ ] 14. erklären und demonstrieren, wie ein minimaler API Token rotiert wird
- [ ] 15. erklären, wie ein kompromittiertes Secret ersetzt und Exposition bewertet wird
- [ ] 16. vollständigen Ablauf bei Droplet-Verlust erklären und mindestens isoliert proben
- [ ] 17. Monitoringchecks, Alarmempfänger und Eskalationsweg finden; Testalarm bestätigen
- [ ] 18. wissen, wer bei technisch oder fachlich nicht selbst lösbarem Problem zuständig ist

### Acceptance-Protokoll

```text
Durchgeführt von:
Beobachtet von:
Datum:
Umgebung:
Bestanden:
Nicht bestanden:
Abweichungen/Follow-ups:
Wiederholung bis:
Unterschrift Technical Owner:
Unterschrift Business Owner:
```

## Aktuell offene Blocker

1. Repository liegt unter persönlichem GitHub-Owner; nur `PhiluLan` als Admin verifiziert.
2. DigitalOcean-, Domain/DNS-, Anny- und Billing-Ownership/MFA/Recovery nicht organisatorisch nachgewiesen.
3. Kein verifiziertes automatisches, verschlüsseltes Offsite-Backup und kein unabhängiger Vollrestore.
4. Kein nachgewiesener organisatorischer Secret-Manager/Break-glass.
5. SQLite-Verlust ist ohne Backup nicht automatisch aus Anny rekonstruierbar.
6. Root-/Passwort-SSH aktiv; Key-Owner nicht vollständig inventarisiert.
7. Monitoring/Alarme/Empfänger nicht verifiziert.
8. alter überberechtigter Anny-Token aktiv.
9. gemeinsames personengebundenes Dashboard-Credential.
10. Deployment/Rollback/DR noch nicht vom Nachfolger praktisch abgenommen.
11. Anny-Kapazität und physischer Tischbedarf können fachlich auseinanderlaufen.

## Technical Handover Status

- [x] **NICHT ÜBERGABEBEREIT** – aktueller Auditstand 1. September 2026
- [ ] **BEDINGT ÜBERGABEBEREIT**
- [ ] **VOLLSTÄNDIG ÜBERGABEBEREIT**

```text
Offene Blocker:
- siehe Liste oben

Übergeben von:
xxx

Übernommen von:
xxx

Datum:
xxx
```

Der Status darf nur nach bestandenem Acceptance Test, geschlossenen P0-Blockern und schriftlicher Bestätigung des Business und Technical Owner angehoben werden.
