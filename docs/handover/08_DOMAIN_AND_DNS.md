# 08 – Domain and DNS

Stand der DNS-/TLS-Abfrage: 1. September 2026

## Verifizierter Ist-Zustand

| Objekt | Wert |
| --- | --- |
| öffentlicher Hostname | `webhook.voltabreau.ch` |
| A-Record | `138.68.87.128` |
| A-TTL | 3600 Sekunden beim Audit |
| AAAA | keiner gefunden |
| CAA | keiner gefunden |
| autoritative Nameserver | `ns1.hosttech.ch`, `ns2.hosttech.ch`, `ns3.hosttech.ch` |
| SOA-Kontakt | `dns.hosttech.eu` in der technischen SOA-Angabe |
| Reverse Proxy | Caddy auf dem DigitalOcean-Droplet |
| TLS | Let's Encrypt, automatische Verwaltung durch Caddy |

Die Nameserver deuten auf DNS-Betrieb bei Hosttech. Registrar, rechtlicher Domaininhaber, Account-Owner, MFA, Billing und Recovery wurden nicht verifiziert.

**HANDOVER BLOCKER / TODO – vor finaler Übergabe verifizieren:** Registrar- und DNS-Account in die Ownership-Matrix aufnehmen, zwei Administratoren und Recovery/Verlängerung testen.

## Auffällige Schreibweise

Der technische Host lautet `webhook.voltabreau.ch`. Die E-Mail-/Dashboard-Domain lautet dagegen `voltabraeu.ch`. Diese Differenz ist real konfiguriert. Bei jeder DNS-, Caddy- oder Anny-Änderung den exakten Hostnamen kopierfrei prüfen; ein scheinbar korrigierter Name wäre eine andere Domain.

## Benötigte DNS Records

Für die aktuelle IPv4-Topologie ist mindestens erforderlich:

```text
Typ: A
Name: webhook
Ziel: 138.68.87.128
TTL: 3600
```

Keinen AAAA-Record setzen, solange der Server nicht nachweislich über dieselbe Anwendung/Firewall auf dieser IPv6 erreichbar ist. Ein falscher AAAA-Record kann bei IPv6-fähigen Clients sporadische Ausfälle erzeugen.

Ein CAA-Record ist nicht zwingend. Falls später einer eingeführt wird, muss Let's Encrypt ausdrücklich erlaubt und die Änderung vor Produktion getestet werden.

## Rolle von Caddy

Caddy:

- lauscht auf 80/443,
- leitet HTTP auf HTTPS um,
- beschafft und erneuert das Zertifikat,
- terminiert TLS,
- leitet intern an `allocator:8099` weiter.

Port 8099 darf nicht öffentlich in DNS oder Firewall exponiert werden. Die Caddy-Konfiguration steht versioniert in `Caddyfile`; Zertifikatszustand liegt in Docker-Volume `caddy_data` und kann bei korrektem DNS neu erzeugt werden.

## DNS prüfen

Von einem unabhängigen Rechner:

```bash
dig +short webhook.voltabreau.ch A
dig @ns1.hosttech.ch webhook.voltabreau.ch A +noall +answer
dig voltabreau.ch NS +short
curl --fail --silent --show-error https://webhook.voltabreau.ch/health
```

Zertifikat und Hostname:

```bash
echo | openssl s_client -connect webhook.voltabreau.ch:443 -servername webhook.voltabreau.ch 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

Beim Audit war das Zertifikat für `webhook.voltabreau.ch` gültig und die TLS-Prüfung erfolgreich. Zertifikatsdaten sind zeitabhängig; Monitoring muss Ablauf/Erneuerung laufend prüfen.

## Serverwechsel

Ein Serverwechsel verändert nicht automatisch Anny, solange der öffentliche Hostname identisch bleibt.

### Vorbereitung

1. Ownership und Wartungsfenster bestätigen.
2. aktuelles konsistentes Offsite-DB-Backup und Secret-Manager prüfen.
3. neuen Server gemäß [12_DISASTER_RECOVERY.md](12_DISASTER_RECOVERY.md) aufbauen.
4. intern Allocator/SQLite prüfen, ohne produktiven Webhookverkehr zuzulassen.
5. neue öffentliche IPv4 und Firewall 22/80/443 verifizieren.
6. bei geplantem Wechsel TTL mindestens 24 Stunden vorher kontrolliert reduzieren; derzeitiger Wert 3600 ist bereits relativ kurz. Diese Änderung selbst braucht Freigabe.

### Umschalten

1. Letztes konsistentes Backup und Ereigniszeit erfassen.
2. alten Allocator kontrolliert aus dem Schreibbetrieb nehmen, damit nicht zwei DB-Stände aktiv sind.
3. A-Record `webhook` auf die neue verifizierte IPv4 ändern.
4. autoritative Nameserver und mehrere Resolver prüfen.
5. Caddy-Logs beobachten, bis ein gültiges Zertifikat für den Host vorliegt.
6. `/health`, Dashboard und Anny-Testbuchung prüfen.
7. Anny-Webhook-URL bleibt unverändert; Call History muss HTTP 200 zeigen.
8. alten Server bis nach vollständiger Beobachtungs-/Rollbackfrist nicht löschen.

### Rollback des DNS-Wechsels

Nur wenn der alte Server mit konsistentem aktuellen DB-Zustand noch eindeutig der aktive Writer sein kann, A-Record auf die alte IP zurücksetzen. Niemals zwei Allocator-Instanzen mit auseinanderlaufenden DBs gleichzeitig aktiv lassen. Daten-/Eventlücke zuerst bestimmen.

## Was bei Ablauf/Verlust der Domain passiert

Anny-Webhooks und Dashboard fallen aus, selbst wenn der Droplet läuft. Direkter Zugriff per IP ist wegen TLS/Hostheader kein gleichwertiger Ersatz. Deshalb sind Domainverlängerung, Billing, MFA, Recovery-Mail und mindestens zwei organisatorische Admins Teil der P0-Übergabe.

## Noch offen

- TODO – vor finaler Übergabe verifizieren: Registrar, Domaininhaber und Vertragskonto
- TODO – vor finaler Übergabe verifizieren: Ablauf-/Verlängerungsdatum und Zahlungsmittel
- TODO – vor finaler Übergabe verifizieren: DNS-Accountadmins, MFA und Recovery-Codes
- TODO – vor finaler Übergabe verifizieren: DigitalOcean Cloud Firewall und mögliche IPv6-Konfiguration
- RECOMMENDED: DNS-/TLS-Verfügbarkeitsmonitoring aus mindestens einer externen Region
