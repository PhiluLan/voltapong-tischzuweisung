# 02 – Access and Ownership

Stand der Prüfung: 1. September 2026

## Grundsatz

Technisches Ownership besteht nur, wenn Volta Bräu Account-Administration, MFA, Recovery, Billing, Credentials und mindestens zwei namentliche technische Administratoren kontrolliert. Ein funktionierender Login auf Philipps Gerät ist kein organisatorischer Besitznachweis.

Keine Credential-Werte werden in diesem Dokument geführt. Als Ziel dient ein von Volta Bräu kontrollierter Passwort-/Secret-Manager mit dokumentiertem Break-glass-Zugriff.

## Ownership-Matrix

| System | Zweck | Owner | Technischer Admin | Login/Account | MFA | Recovery-Verfahren | Credential-Speicherort | Offboarding-Schritt | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GitHub-Repository | Code, Tests, Dokumentation | aktuell persönlicher GitHub-Owner `PhiluLan`; Ziel: Volta-Bräu-Organisation | aktuell nur `PhiluLan` als Admin verifiziert | persönlicher GitHub-Account | TODO – vor finaler Übergabe verifizieren | GitHub-Org-Recovery und mindestens zwei Owner einrichten | keine GitHub-Tokens in Git; organisatorischer Secret-Manager | Repository übertragen, Organisationsadmins testen, Philipps Zugriff entfernen | **HANDOVER BLOCKER** |
| DigitalOcean | Droplet, Netzwerk, optionale Backups | xxx – organisatorisch festlegen | xxx – organisatorisch festlegen | DigitalOcean-Teamkonto unbekannt | TODO – vor finaler Übergabe verifizieren | Team-Owner, Recovery-Mail/-Codes und zweiter Admin dokumentieren | organisatorischer Secret-Manager | Philipps Teamzugriff erst nach getesteter Übernahme entfernen | **HANDOVER BLOCKER** |
| Produktionsserver | Betriebssystem und Laufzeit | Ziel: Volta Bräu | xxx – organisatorisch festlegen | derzeit SSH als `root` verifiziert | SSH selbst ohne MFA; Provider-MFA separat | DigitalOcean Console/Recovery und Break-glass-Key dokumentieren | öffentliche Keys auf Server; private Keys nur beim jeweiligen Admin | neuen Admin testen, Philipps Key entfernen, Root-Zugang härten | **HIGH PRIORITY** |
| SSH | Wartungs-/Notfallzugriff | Ziel: Volta Bräu | namentliche Admins fehlen | aktuell Root-Key und Passwortlogin möglich | nicht vorhanden | Provider-Konsole plus offline verwahrter Break-glass-Zugang | private Keys nie zentral kopieren; Recovery-Key verschlüsselt | Key-Fingerprint inventarisieren und Philipps Key entfernen | **HANDOVER BLOCKER** bis Schlüsselzuordnung geklärt |
| Domain `voltabreau.ch` | Namensraum für Produktionshost | xxx – organisatorisch festlegen | xxx – organisatorisch festlegen | Registrar-Account unbekannt | TODO – vor finaler Übergabe verifizieren | Registrar-Recovery-Mail, MFA und Billing dokumentieren | organisatorischer Passwort-Manager | persönlichen Registrarzugriff entfernen | **HANDOVER BLOCKER** |
| DNS-Zone | A-Record für `webhook.voltabreau.ch` | xxx – organisatorisch festlegen | xxx – organisatorisch festlegen | Nameserver deuten auf Hosttech; Account nicht geprüft | TODO – vor finaler Übergabe verifizieren | zweiter DNS-Admin und Recovery-Verfahren festlegen | organisatorischer Passwort-Manager | Philipps DNS-Zugriff entfernen | **HANDOVER BLOCKER** |
| Anny-Organisation | führendes Buchungssystem | Ziel: Volta Pong/Volta Bräu; tatsächlicher Owner nicht geprüft | eingeloggter Nutzer Philipp Langer sichtbar; Rolle nicht verifiziert | organisatorische Benutzerliste unbekannt | TODO – vor finaler Übergabe verifizieren | mindestens zwei Organisationsadmins und Recovery-Mail prüfen | Anny Accountverwaltung | Philipps Benutzer nach Funktionsübergabe entfernen | **HANDOVER BLOCKER** |
| Anny API Credential | Buchungen lesen/aktualisieren | Ziel: Volta Bräu | Anny-Admins | PAT „Volta Pong Tischzuweisung v3“; Wert nie dokumentieren | nicht auf Tokenebene | neuen minimalen Token über Anny-Admin erzeugen | Secret-Manager und Produktions-`.env` als Deploymentkopie | neuen Token testen, alten widerrufen | aktiv, Ablauf 1. September 2027; Ownership offen |
| alter Anny API Token | historische API-Nutzung | unbekannt/persönliche Altlast | Anny-Admins | PAT „annyAPI“ | nicht auf Tokenebene | durch minimalen Token ersetzen | Wert nicht erfassen | nach Übergabetest widerrufen | **HIGH PRIORITY**, aktiv und überberechtigt |
| Webhook Credential | Authentifiziert Anny→Allocator | Ziel: Volta Bräu | Anny- und Serveradmins | identischer Secret-Wert in Anny-URL und Server-`.env` | nicht anwendbar | neuen Zufallswert erzeugen, beide Seiten kontrolliert umstellen | Secret-Manager; Deploymentkopie in `.env` | bei Austritt/Leak rotieren | aktiv; organisatorischer Speicherort offen |
| Dashboard | lesender Betriebsstatus | Ziel: Volta Bräu | technischer Admin | gemeinsames Basic-Auth-Konto; derzeitiger Benutzer `planger@voltabraeu.ch` | keine MFA/Rollen/Recovery | neues Passwort in `.env` setzen und Container neu starten | Secret-Manager | Login auf Teamkonto umstellen, Passwort rotieren | **HIGH PRIORITY**, persönliche Benennung |
| Backup-System | Restore von DB/Konfiguration | Ziel: Volta Bräu | xxx – organisatorisch festlegen | nur lokale Backups auf Droplet verifiziert | TODO – vor finaler Übergabe verifizieren | Offsite-Backupkonto, Recovery-Key und Restore-Test fehlen | verschlüsselter Offsite-Speicher | Zugriff testen und Philipps Rechte entfernen | **HANDOVER BLOCKER** |
| Monitoring | Ausfälle erkennen und alarmieren | Ziel: Volta Bräu | xxx – organisatorisch festlegen | externer Dienst/Empfänger nicht verifiziert | TODO – vor finaler Übergabe verifizieren | zweiter Alarmempfänger und Account-Recovery | organisatorischer Passwort-Manager | Empfänger und Adminrechte aktualisieren | **HANDOVER BLOCKER** für belastbaren Betrieb |
| Rechnungen/Billing | Fortbestand von Droplet, Domain, Anny, Monitoring | Ziel: Volta Bräu | xxx – organisatorisch festlegen | Accounts/Zahlungsmittel nicht geprüft | TODO – vor finaler Übergabe verifizieren | Finance-Kontakt, zweite Zahlart und Verlängerungsalarm | Finanz-/Accountsystem von Volta Bräu | persönliche Zahlart/Adresse entfernen | **HANDOVER BLOCKER** |

## Verifizierte Zugangsoberflächen

- GitHub: `https://github.com/PhiluLan/voltapong-tischzuweisung`
- Produktionsserver: SSH auf `138.68.87.128`, Port 22
- DigitalOcean: Control Panel des noch zu identifizierenden Teams
- Anny: Organisations-/Account-Einstellungen → API
- Dashboard: `https://webhook.voltabreau.ch/dashboard`
- DNS: Nameserver `ns1.hosttech.ch`, `ns2.hosttech.ch`, `ns3.hosttech.ch`; konkreter Account unbekannt

## Mindestrollen für den Zielzustand

| Rolle | Mindestbesetzung | Rechte |
| --- | ---: | --- |
| Business Owner | 1 plus Vertretung | Verträge, Billing, Eskalationsentscheidung |
| Technical Owner | 1 plus Vertretung | GitHub, Server, Anny API, DNS, Monitoring, Restore |
| GitHub Organization Owner | 2 | Repository, Teams, Recovery, Security Settings |
| DigitalOcean Team Owner | 2 | Droplet, Backups, Netzwerk, Billing/Recovery |
| Anny Organization Admin | 2 | Webhooks, Tokens, Benutzer, Recovery |
| DNS/Domain Admin | 2 | Records, Transfer, Verlängerung, Recovery |
| Incident Contact | Primär + Backup | Alarmannahme und Eskalation |

Personen dürfen mehrere Rollen ausfüllen, aber keine kritische Plattform darf nur an einem persönlichen Account hängen.

## Vor Entfernen von Philipps Zugriff

1. Ziel-Owner und Stellvertretung namentlich eintragen.
2. MFA und Recovery auf jeder Plattform mit beiden Personen testen.
3. Eigenen SSH-Zugang und Provider-Konsole testen.
4. Offsite-Backup herunterladen und Restore in isolierter Umgebung durchführen.
5. Deployment und Rollback unter Beobachtung absolvieren.
6. Alle Secrets rotieren, auf die Philipp Zugriff hatte.
7. Monitoringalarm an neue Empfänger testweise auslösen.
8. Billing-/Verlängerungsinformationen bestätigen.
9. Erst dann Philipps persönliche Keys, Accounts und Rechte entfernen.

## Noch zu erhebende organisatorische Nachweise

- TODO – vor finaler Übergabe verifizieren: rechtlicher Domaininhaber, Registrarvertrag und Verlängerungsdatum
- TODO – vor finaler Übergabe verifizieren: DigitalOcean-Teamowner, Zahlungsmittel, Droplet-Backups und Recovery-Mail
- TODO – vor finaler Übergabe verifizieren: Anny-Owner/Adminliste, MFA, Billing und Recovery
- TODO – vor finaler Übergabe verifizieren: Zuordnung aller auf dem Server erlaubten SSH-Key-Fingerprints
- TODO – vor finaler Übergabe verifizieren: heutiger Secret-Speicherort und Break-glass-Verfahren
- TODO – vor finaler Übergabe verifizieren: Monitoringanbieter, Alarmempfänger und Eskalationsvertrag
