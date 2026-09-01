# Laienhandbuch: Volta-Pong-Tischzuweisung

Stand: 1. September 2026

## Das System in einem Satz

Gäste buchen weiterhin ganz normal über Anny. Ein kleines Programm auf einem DigitalOcean-Server erhält jede Buchungsänderung automatisch, sucht passende freie Tische und schreibt die Tischnummer zurück nach Anny und damit auch in die Bestätigungsmail.

## Die wichtigsten Adressen

| Zweck | Adresse |
| --- | --- |
| Mitarbeiter-Dashboard | `https://webhook.voltabreau.ch/dashboard` |
| Öffentliche Funktionsprüfung | `https://webhook.voltabreau.ch/health` |
| Quellcode und Dokumentation | `https://github.com/PhiluLan/voltapong-tischzuweisung` |
| Anny-Webhook-Verwaltung | Anny Admin → Account Settings → API |
| Serververwaltung | DigitalOcean Control Panel |

Der Dashboard-Benutzername ist `planger@voltabraeu.ch`. Das Passwort liegt nur in der geschützten Serverkonfiguration und darf nicht in GitHub oder in dieses Handbuch geschrieben werden.

Wichtig: Die aktuelle technische Adresse lautet `webhook.voltabreau.ch`. Die Schreibweise unterscheidet sich von der E-Mail-Domain `voltabraeu.ch`. Das ist momentan tatsächlich so konfiguriert und kein Schreibfehler dieses Handbuchs.

## Wer macht was?

```text
Gast
  │ bucht oder storniert
  ▼
Anny ── Webhook ──► webhook.voltabreau.ch
                         │
                         ▼
                DigitalOcean-Server
                ├─ Caddy: HTTPS und Weiterleitung
                ├─ Allocator: sucht freie Tische
                └─ SQLite: merkt sich die Belegung
                         │
                         └──► schreibt Tisch(e) über die Anny-API zurück

Mitarbeiter ── Browser ──► geschütztes Dashboard
Entwickler   ── GitHub/SSH ► Code und Serverbetrieb
```

### Anny

Anny bleibt das führende Buchungssystem. Dort liegen Buchung, Zeitraum, Status, Service und Kundenkommunikation. Die Tischzuweisung ersetzt Anny nicht, sondern ergänzt jede relevante Buchung um konkrete Tischnummern.

### Webhook

Ein Webhook ist eine automatische Nachricht von Anny an unser Programm. Bei `bookings.created`, `bookings.updated` und `bookings.deleted` übermittelt Anny mindestens den Ereignistyp und die Buchungs-ID. Das Programm lädt anschließend den aktuellen Buchungsstand direkt über die Anny-API.

Ein Webhook ist mit einem geheimen Schlüssel geschützt. Der Schlüssel steht weder im GitHub-Repository noch im Dashboard.

### DigitalOcean und der Droplet

DigitalOcean vermietet den virtuellen Computer, auf dem das Programm rund um die Uhr läuft. Dieser virtuelle Computer heißt bei DigitalOcean „Droplet“.

Der aktuelle Droplet:

- öffentliche IP-Adresse: `138.68.87.128`
- Region/Hostname: `fra1` beziehungsweise `ubuntu-s-1vcpu-1gb-fra1-01`
- Betriebssystem: Ubuntu 24.04.3 LTS
- Leistung: 1 CPU, rund 1 GB RAM, 24 GB Festplatte
- Server-Zeitzone: UTC; die Buchungen werden fachlich für `Europe/Zurich` verarbeitet

DigitalOcean ist also nicht die Tischzuweisung selbst. Es stellt nur den dauernd erreichbaren Computer bereit.

### Domain und DNS

`webhook.voltabreau.ch` ist die öffentliche Adresse des Servers. DNS übersetzt diesen Namen zur IP-Adresse des Droplets. Eine Domain ist technisch nicht zwingend; Anny könnte auch eine dauerhaft bereitgestellte Plattformadresse verwenden. Eine eigene Domain ist dennoch sinnvoll, weil sie stabil, verständlich und unabhängig vom Serveranbieter bleibt.

Die Domain ist nicht „der Server“. Sie ist eher das Adressschild, das auf den Server zeigt.

### Caddy und HTTPS

Caddy nimmt Anfragen auf den öffentlichen Ports 80 und 443 entgegen, leitet HTTP automatisch auf HTTPS um, verwaltet das TLS-Zertifikat und reicht die Anfrage intern an die Tischzuweisung weiter. Der eigentliche Allocator-Port 8099 ist nicht direkt aus dem Internet veröffentlicht.

### Ubuntu

Ubuntu ist das Betriebssystem des Droplets, vergleichbar mit macOS auf einem Mac. Es startet Docker, stellt Firewall und Updates bereit und ermöglicht Wartungszugriff per SSH.

### Docker

Docker startet zwei voneinander getrennte Container:

- `anny_webhook-allocator-1`: Tischlogik, Dashboard und SQLite-Zugriff
- `anny_webhook-caddy-1`: Domain, HTTPS und Weiterleitung

Der Allocator startet nach einem Serverneustart automatisch wieder, besitzt ein schreibgeschütztes Systemdateisystem und meldet seinen Zustand per Healthcheck.

### SQLite

SQLite ist eine kleine Datenbankdatei unter `/opt/anny_webhook/data/allocator.db`. Sie enthält die berechnete Tischbelegung und verarbeitete Webhook-IDs, aber keine eigene Benutzerverwaltung. Anny bleibt die fachliche Quelle; SQLite ist die Arbeitskarte der Tischzuweisung.

### GitHub

GitHub enthält Quellcode, Tests und Dokumentation. Der produktive Code basiert aktuell auf Commit `c261d029d8929582aa8d0628267c79003e0093be`.

Wichtig: Ein Push nach GitHub wird derzeit noch nicht automatisch auf den Server ausgerollt. GitHub ist die freigegebene Code-Wahrheit; ein kontrollierter Deployment-Schritt macht daraus den laufenden Serverstand.

### Terminal und SSH

Das Terminal ist eine Texteingabe für technische Wartung. SSH ist die verschlüsselte Verbindung vom Mac zum Ubuntu-Server. Gäste und normale Mitarbeiter brauchen weder Terminal noch SSH.

Der heutige Wartungszugang lautet:

```bash
ssh root@138.68.87.128
```

Der Benutzer `root` darf alles auf dem Server. Deshalb sollten diesen Zugang nur technisch Verantwortliche benutzen. Mittelfristig soll er durch einen persönlichen SSH-Schlüssel und einen eingeschränkten Wartungsbenutzer ersetzt werden.

## Was passiert bei einer neuen Buchung?

1. Der Gast bucht in Anny.
2. Anny sendet einen `bookings.created`-Webhook.
3. Der Allocator lädt die aktuelle Buchung über die Anny-API.
4. Aus Buchungsgewicht beziehungsweise Service wird der Tischbedarf bestimmt.
5. SQLite liefert die bereits belegten Tische im überschneidenden Zeitraum.
6. Das Programm wählt zuerst eine zusammenhängende freie Tischgruppe, ansonsten freie einzelne Tische.
7. Die Zuweisung wird in SQLite gespeichert.
8. `customer_note`, interne Notiz und Beschreibung werden in Anny aktualisiert.
9. Die Tischangabe erscheint auch in der Bestätigungsmail.

## Was passiert bei einem Storno?

1. Anny sendet je nach Bedienweg ein `bookings.updated` mit Storno-Status oder ein `bookings.deleted`.
2. Der Allocator erkennt beide Varianten.
3. Die alte Allocation wird entfernt; ihre Tische sind sofort wieder frei.
4. Wartende, bislang nicht zuweisbare Buchungen für denselben Zeitraum werden erneut geprüft.
5. Eine neue Buchung kann den freigewordenen Tisch erhalten.

Der produktive Test vom 1. September 2026 hat diesen Ablauf bestätigt: `BB783001256` gab Tisch 8 frei; die anschließende Buchung `BB855734593` erhielt automatisch Tisch 8 und die Tischangabe erschien in der E-Mail.

## Gleichzeitige Buchungen

Der komplette Vorgang „Belegung lesen → Tisch wählen → speichern“ ist im einzelnen Allocator-Prozess gesperrt. Zwei nahezu gleichzeitige Webhooks können dadurch nicht denselben Tisch auswählen. Deshalb darf produktiv nur ein Allocator-Prozess laufen, solange SQLite verwendet wird.

## Das Dashboard benutzen

1. Im Browser `https://webhook.voltabreau.ch/dashboard` öffnen.
2. Im Browser-Dialog den Benutzernamen `planger@voltabraeu.ch` eingeben.
3. Das vereinbarte Dashboard-Passwort eingeben.

Der Zugang ist ein einzelner geschützter Dashboard-Login. „Super Admin“ bedeutet hier nicht dasselbe wie in Anny: Das Dashboard ist momentan nur lesbar und kann keine Buchungen verändern.

### Bedeutung der Ampel

- **Grün:** keine erkannten Tischkollisionen und keine relevanten offenen Fälle.
- **Gelb:** offene `unassigned`-Buchungen, ein noch retry-fähiger Fehler, ungültige Daten oder eine leere Datenbank.
- **Rot:** derselbe Tisch wurde für überschneidende Buchungen erkannt.

Das Dashboard aktualisiert sich ungefähr alle 30 Sekunden. Es zeigt den SQLite- und Webhook-Zustand, führt aber keinen vollständigen permanenten Vergleich aller Anny-Buchungen durch.

## Was ist im normalen Alltag zu tun?

Meistens nichts. Das System läuft automatisch.

Bei einer auffälligen Buchung:

1. Buchungsnummer und Zeitraum notieren.
2. Prüfen, ob in der Anny-Buchung „Deine Tische“ steht.
3. Dashboard öffnen und Ampelfarbe ansehen.
4. Bei Gelb oder Rot Screenshot, Buchungsnummer und Uhrzeit an die technische Betreuung senden.
5. Nicht manuell in SQLite ändern.

## Einfache Funktionsprüfung

`https://webhook.voltabreau.ch/health` muss eine erfolgreiche Antwort liefern. Das bedeutet: Webserver und Datenbank sind erreichbar. Es beweist noch nicht, dass Anny gerade Webhooks zustellt oder jede Buchung fachlich korrekt ist.

## Technische Wartung im Terminal

Nach erfolgreicher SSH-Anmeldung:

```bash
cd /opt/anny_webhook
docker compose ps
docker compose logs --tail=100 allocator
```

- `docker compose ps` zeigt, ob Allocator und Caddy laufen.
- Beim Allocator sollte `healthy` stehen.
- `docker compose logs --tail=100 allocator` zeigt die letzten technischen Meldungen.
- Mit `exit` wird die SSH-Verbindung beendet.

Nicht ohne getesteten Plan verwenden: `rm`, manuelle SQLite-Änderungen, Container löschen, `.env` überschreiben oder einen zweiten Allocator starten.

## Dateien auf dem Server

| Pfad | Bedeutung |
| --- | --- |
| `/opt/anny_webhook` | produktive Anwendung |
| `/opt/anny_webhook/app.py` | Tischlogik und Dashboard-API |
| `/opt/anny_webhook/docker-compose.yml` | Containerdefinition |
| `/opt/anny_webhook/Caddyfile` | Domain und HTTPS-Weiterleitung |
| `/opt/anny_webhook/.env` | geheime Zugangsdaten und Einstellungen; niemals nach GitHub kopieren |
| `/opt/anny_webhook/data/allocator.db` | produktive SQLite-Datenbank |
| `/opt/anny_webhook/backups` | lokale Sicherungen vor Änderungen |

## Backup und Wiederherstellung

Vor riskanten Änderungen wird die laufende SQLite-Datenbank mit der SQLite-Backup-Funktion konsistent gesichert. Die vorhandenen lokalen Sicherungen schützen gegen fehlerhafte Deployments, aber nicht gegen einen vollständigen Verlust des Droplets. Deshalb gehören automatische DigitalOcean-Backups oder zusätzliche verschlüsselte Offsite-Backups zu den nächsten Betriebsverbesserungen.

Ein Restore ist eine technische Notfallmaßnahme und wird nicht im normalen Betrieb durchgeführt.

## Bekannte Punkte

1. **Anny-Kapazität und Tischbedarf können auseinanderlaufen.** Anny kann „8 Buchungen“ beziehungsweise „8/8“ anzeigen, während Services unterschiedlich viele physische Tische benötigen. Am 7. September waren deshalb in Anny keine weiteren Buchungen möglich, obwohl SQLite nur sechs Tische konkret zugeordnet hatte und eine Vier-Tisch-Buchung offen blieb. Das ist ein eigener fachlicher Konfigurations-/Modellierungsfehler und kein übrig gebliebener E2E-Testblocker.
2. **Das Dashboard kennt nur einen gemeinsamen Login.** Mehrere Benutzer, Rollen, Passwort-Reset und Zwei-Faktor-Anmeldung existieren dort noch nicht.
3. **Deployment ist noch manuell.** GitHub und Produktion sind geprüft gleich, bleiben aber zwei getrennte Schritte.
4. **SSH ist momentan zu mächtig.** Root- und Passwort-Anmeldung sind noch aktiviert.
5. **Der alte Anny-Token `annyAPI` ist noch aktiv.** Der Server verwendet bereits den neuen minimal berechtigten Token; der alte Token bleibt auf ausdrücklichen Wunsch bis nach weiteren Tests bestehen.

## Begriffe kurz erklärt

| Begriff | Einfache Erklärung |
| --- | --- |
| API | geregelte Schnittstelle, über die Programme Daten austauschen |
| Webhook | automatische Nachricht von Anny an unser Programm |
| Server/Droplet | dauernd laufender virtueller Computer im Internet |
| Domain | lesbarer Name, der auf den Server zeigt |
| DNS | Telefonbuch, das Domain und IP-Adresse verbindet |
| HTTPS/TLS | verschlüsselte und zertifizierte Webverbindung |
| Caddy | Eingangstür des Servers; kümmert sich um HTTPS und Weiterleitung |
| Docker/Container | verpackte Laufzeit für reproduzierbaren Betrieb |
| SQLite | einzelne Datenbankdatei für die Tischbelegung |
| Terminal | Texteingabe für technische Befehle |
| SSH | verschlüsselte Fernverbindung zum Server |
| GitHub | Versionsverwaltung für Code und Dokumentation |

## Weiterführende Dokumente

- [ARCHITECTURE.md](ARCHITECTURE.md): technische Fachlogik
- [OPERATIONS.md](OPERATIONS.md): Deployment, Backup und Rollback
- [CURRENT_STATE.md](CURRENT_STATE.md): aktuell belegter Produktionsstand
- [ZUKUNFT.md](ZUKUNFT.md): Bewertung der Infrastruktur und empfohlene Entwicklung

