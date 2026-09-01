# Technical Handover Package

Stand der technischen Prüfung: 1. September 2026

## Zweck und Zielgruppe

Dieses Verzeichnis ist der betriebliche Einstiegspunkt für die Volta-Pong-Tischzuweisung. Es richtet sich an einen technisch kompetenten Nachfolger oder externen Entwickler mit Grundkenntnissen in Python, Git, Docker und Linux. Die Dokumente sollen Betrieb und Wiederherstellung ohne Wissen des ursprünglichen Entwicklers ermöglichen.

Das Package beschreibt Ownership, Zugänge, Infrastruktur, Deployment, Rollback, Backup, Restore, Störungsbehandlung, Monitoring, Security und Disaster Recovery. Die fachliche Tischlogik wird nicht erneut vollständig erklärt; dafür gelten [ARCHITECTURE.md](../ARCHITECTURE.md) und die Tests als Referenz.

## Verbindliche Sicherheitsregel

Keine echten Passwörter, Tokens, Webhook-Schlüssel, privaten SSH-Keys oder sonstigen Credentials gehören in Git, Tickets, Chatverläufe oder Screenshots. Beispiele verwenden ausschließlich Platzhalter:

```dotenv
ANNY_TOKEN=xxx
WEBHOOK_SECRET=xxx
DASHBOARD_PASSWORD=xxx
```

Secrets müssen in einem von Volta Bräu kontrollierten Passwort-/Secret-Manager liegen. Ein Wert, der in Git oder einem öffentlich zugänglichen Log erscheint, gilt als kompromittiert und muss rotiert werden.

## Beteiligte Systeme

| System | Rolle | Verifizierter Stand |
| --- | --- | --- |
| GitHub | Quellcode, Tests und Dokumentation | öffentliches Repository unter persönlichem Owner `PhiluLan`; Audit-Ausgangsstand vor diesem Package `97ad2192...` |
| DigitalOcean | virtueller Produktionsserver | Droplet in `fra1`, öffentliche IP `138.68.87.128` |
| Ubuntu/Docker | Laufzeit | Ubuntu 24.04.3 LTS; zwei Compose-Container |
| Caddy | HTTPS und Reverse Proxy | `webhook.voltabreau.ch` → interner Allocator-Port 8099 |
| Allocator | Webhook, Anny-API, Dashboard, Tischzuweisung | Anwendungsversion 3.0.0; produktiver Code-Commit `c261d029...` |
| SQLite | abgeleiteter Belegungs- und Eventzustand | `/opt/anny_webhook/data/allocator.db` |
| Anny | führendes Buchungssystem | Webhook für create/update/delete; API read/update |
| DNS | Domainauflösung | A-Record zeigt auf `138.68.87.128`; Nameserver bei Hosttech |

Die Angabe eines Providers ist noch kein nachgewiesenes organisatorisches Ownership. Ungeklärte Zuständigkeiten stehen in [02_ACCESS_AND_OWNERSHIP.md](02_ACCESS_AND_OWNERSHIP.md).

## Empfohlene Lesereihenfolge

1. [01_SYSTEM_OVERVIEW.md](01_SYSTEM_OVERVIEW.md) – Systemgrenzen und Laufzeitbild
2. [02_ACCESS_AND_OWNERSHIP.md](02_ACCESS_AND_OWNERSHIP.md) – Accounts, Verantwortung und Recovery
3. [03_PRODUCTION_SERVER.md](03_PRODUCTION_SERVER.md) – tatsächlicher Server und sichere Diagnose
4. [04_DEPLOYMENT.md](04_DEPLOYMENT.md) – Release und Rollback
5. [05_BACKUP_AND_RESTORE.md](05_BACKUP_AND_RESTORE.md) – Sicherung und Wiederherstellung
6. [06_INCIDENT_RUNBOOK.md](06_INCIDENT_RUNBOOK.md) – konkrete Störungsfälle
7. [07_ANNY_CONFIGURATION.md](07_ANNY_CONFIGURATION.md) und [08_DOMAIN_AND_DNS.md](08_DOMAIN_AND_DNS.md)
8. [09_MONITORING.md](09_MONITORING.md), [10_SECURITY_AND_SECRETS.md](10_SECURITY_AND_SECRETS.md) und [11_MAINTENANCE.md](11_MAINTENANCE.md)
9. [12_DISASTER_RECOVERY.md](12_DISASTER_RECOVERY.md) – vollständiger Droplet-Verlust
10. [HANDOVER_CHECKLIST.md](HANDOVER_CHECKLIST.md) – tatsächliche Übergabe und Acceptance Test

Ergänzende Referenzen:

- [CURRENT_STATE.md](../CURRENT_STATE.md): verifizierter fachlicher und technischer Produktionsstand
- [OPERATIONS.md](../OPERATIONS.md): bisherige kompakte Betriebsnotizen
- [SECURITY.md](../../SECURITY.md): allgemeine Repository-Sicherheitsregeln
- [HANDBUCH.md](../HANDBUCH.md): Anleitung für nichttechnische Mitarbeitende
- [ZUKUNFT.md](../ZUKUNFT.md): bewertete Infrastrukturvarianten

## Wo liegen die wichtigsten Betriebsanleitungen?

| Aufgabe | Dokument |
| --- | --- |
| Zustand in zehn Minuten prüfen | [03_PRODUCTION_SERVER.md](03_PRODUCTION_SERVER.md#server-kennenlernen-in-10-minuten) |
| Neue Version deployen | [04_DEPLOYMENT.md](04_DEPLOYMENT.md) |
| Zurückrollen | [04_DEPLOYMENT.md](04_DEPLOYMENT.md#rollback) |
| SQLite sichern oder wiederherstellen | [05_BACKUP_AND_RESTORE.md](05_BACKUP_AND_RESTORE.md) |
| Störung diagnostizieren | [06_INCIDENT_RUNBOOK.md](06_INCIDENT_RUNBOOK.md) |
| Token/Secret rotieren | [10_SECURITY_AND_SECRETS.md](10_SECURITY_AND_SECRETS.md) |
| Kompletten Server neu aufbauen | [12_DISASTER_RECOVERY.md](12_DISASTER_RECOVERY.md) |

## Philipp ist nicht mehr erreichbar – was brauche ich?

Eine neue technische Verantwortung ist erst hergestellt, wenn die folgende Person oder Firma unabhängig über diese Mittel verfügt:

1. Organisationskontrollierter GitHub-Owner oder mindestens zwei Volta-Bräu-Administratoren mit Admin-Rechten auf ein übertragenes Repository.
2. Eigenes DigitalOcean-Teamkonto mit Admin-/Billing-Rechten, aktivem MFA und dokumentiertem Recovery-Kanal.
3. Eigenen namentlichen SSH-Key, getesteten Serverzugang und einen dokumentierten Break-glass-Zugang. Kein privater Schlüssel von Philipp darf kopiert werden.
4. Zugriff auf den organisatorischen Passwort-/Secret-Manager mit Anny-Token, Webhook-Secret, Dashboard-Zugang und Recovery-Informationen.
5. Admin-Zugriff auf Anny einschließlich API-/Webhook-Verwaltung, MFA und Account-Recovery.
6. Zugriff auf Domainregistrar und DNS-Zone einschließlich Billing und Recovery.
7. Zugriff auf mindestens ein geprüftes, verschlüsseltes Offsite-Backup der SQLite-Datenbank und der nicht aus Git rekonstruierbaren Konfiguration.
8. Zugriff auf Monitoring und die Empfänger der Alarme.
9. Einen benannten externen Eskalationskontakt und eine organisatorisch freigegebene Zuständigkeit für Rechnungen.

Fehlt einer der Punkte 1 bis 7, ist ein vollständiger Betrieb oder Wiederaufbau nicht unabhängig gesichert. Der aktuelle Ist-Zustand erfüllt diese Anforderungen noch nicht vollständig; verbindliche Lücken stehen als **HANDOVER BLOCKER** in der Checklist.

## Quellen der Wahrheit

- **Buchungen und Kundendaten:** Anny
- **freigegebener Code und Dokumentation:** GitHub `main`
- **aktuell laufender Code:** OCI-Revision des laufenden Allocator-Images; am 1. September 2026 `c261d029d8929582aa8d0628267c79003e0093be`
- **aktuelle Tischzuweisungen und verarbeitete Events:** produktive SQLite-Datei
- **Secrets:** zukünftiger organisatorischer Secret-Manager; derzeitiger organisatorischer Speicherort ist nicht verifiziert
- **Account- und Billing-Ownership:** jeweilige Providerverwaltung; derzeit teilweise ungeklärt

Ein Push nach GitHub deployt nicht automatisch. Repository-`main` und Produktion müssen deshalb bei jedem Release ausdrücklich abgeglichen werden.
