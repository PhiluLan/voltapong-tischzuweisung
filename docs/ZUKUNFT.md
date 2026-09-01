# Bewertung und Zukunft der Infrastruktur

Stand: 1. September 2026

## Kurzurteil

Die heutige Lösung ist für acht Tische und einen einzelnen seriellen Allocator **sinnvoll und verhältnismäßig**. DigitalOcean, Ubuntu, Docker, Caddy und SQLite sind nicht grundsätzlich falsch oder unnötig. Ein sofortiger Plattformwechsel würde mehr neue Risiken erzeugen als Probleme lösen.

Die wichtigsten Verbesserungen liegen zunächst nicht in einem anderen Anbieter, sondern in:

1. automatischen Offsite-Backups,
2. SSH-Härtung,
3. automatisiertem, nachvollziehbarem Deployment,
4. Behebung des Kapazitätsunterschieds zwischen Anny-Buchungen und physischen Tischen,
5. einem persönlichen Login statt eines gemeinsamen Dashboard-Passworts.

## Brauchen wir DigitalOcean?

Nicht zwingend. Benötigt wird irgendeine Laufzeit, die rund um die Uhr eine öffentliche HTTPS-Adresse beantwortet und Daten dauerhaft speichert.

Der jetzige Droplet passt aber gut, weil:

- die vorhandene Python-/Docker-Anwendung ohne Umbau läuft,
- SQLite dauerhaft auf der Droplet-Festplatte liegt,
- genau ein Prozess benötigt wird,
- der Ressourcenbedarf sehr klein ist,
- Caddy und Docker bereits funktionieren und getestet sind.

Der Nachteil: Betriebssystem, SSH, Firewall, Updates, Backups und Deployment müssen selbst gepflegt werden.

## Brauchen wir eine Domain?

Eine öffentliche HTTPS-Adresse ist zwingend, weil Anny Webhooks an eine erreichbare URL senden muss. Eine eigene Domain ist optional, aber empfehlenswert.

Ohne eigene Domain könnte eine Plattformadresse wie `*.ondigitalocean.app` verwendet werden. Mit eigener Domain kann der Serveranbieter später gewechselt werden, ohne dass sich die Adresse für Anny und Mitarbeiter ändern muss.

Die heutige Adresse `webhook.voltabreau.ch` funktioniert. Wenn `voltabreau.ch` nur eine provisorische oder falsch geschriebene Domain ist, sollte später kontrolliert auf eine eindeutige Adresse wie `tischzuweisung.voltapong.ch` umgestellt werden. Dafür müssen DNS, Caddy und der Anny-Webhook gemeinsam geändert und getestet werden.

## Brauchen wir Ubuntu und SSH?

Nur solange ein eigener virtueller Server betrieben wird.

- Ubuntu führt Docker und die Anwendung aus.
- SSH ermöglicht Wartung und Notfallzugriff.
- Gäste und normale Mitarbeiter brauchen beides nicht.

Auf einer vollständig verwalteten App-Plattform würden Ubuntu- und SSH-Pflege weitgehend entfallen. Dafür entstehen stärkere Plattformabhängigkeit, andere Kosten und bei dieser Anwendung ein Datenbankumbau.

## Drei realistische Varianten

| Variante | Vorteile | Nachteile | Urteil |
| --- | --- | --- | --- |
| Droplet + Docker + Caddy + SQLite behalten | kein Umbau, klein, schnell, bewährt | Serverpflege und SSH bleiben | **Jetzt empfohlen** |
| DigitalOcean App Platform + Managed PostgreSQL | Git-basierte Deployments, weniger Betriebssystempflege, verwaltete Datenbank | Migration von SQLite, neue Sperrlogik, mehr Komponenten und Kosten | sinnvoll bei Wachstum oder gewünschter Managed-Plattform |
| Serverless/Edge + verwaltete Datenbank | kaum Serverbetrieb, automatische Skalierung | größere Neuentwicklung, andere Laufzeit, andere Daten- und Sperrlogik | derzeit unnötig |

## Warum App Platform nicht einfach SQLite übernehmen kann

DigitalOcean dokumentiert das lokale Dateisystem der App Platform als flüchtig: Dateien können bei Deployment oder Containerersatz verloren gehen, und persistente Volumes werden nicht unterstützt. Die bestehende SQLite-Datei dürfte dort deshalb nicht einfach weiterverwendet werden.

Eine Migration auf App Platform verlangt mindestens:

1. SQLite durch PostgreSQL ersetzen,
2. Daten migrieren und Restore testen,
3. die In-Prozess-Sperre durch eine datenbankgestützte Sperre oder Transaktion ersetzen,
4. Secrets in die Plattformkonfiguration übertragen,
5. Webhook und Dashboard unter neuer Adresse testen.

Managed PostgreSQL bietet automatische Backups und kann hochverfügbar betrieben werden. Für acht Tische ist das heute eher Komfort und Betriebssicherheit als eine Leistungsnotwendigkeit.

## Empfohlener Weg

### Phase 1: Bestehende Lösung professionell absichern

1. DigitalOcean-Droplet-Backups aktivieren.
2. Zusätzlich tägliches konsistentes SQLite-Backup verschlüsselt außerhalb des Droplets speichern.
3. Persönlichen Wartungsbenutzer und SSH-Key einrichten.
4. Root-Login und Passwort-Login anschließend deaktivieren.
5. Alten Anny-Token `annyAPI` nach Abschluss der Tests widerrufen.
6. Monitoring ergänzen, das bei rotem Dashboard, wiederholten Webhook-Fehlern oder nicht erreichbarem Healthcheck benachrichtigt.
7. Kapazitätsmodell in Anny so ändern, dass die buchbare Kapazität den tatsächlich benötigten Tischen entspricht.

### Phase 2: GitHub wirklich zur Deployment-Wahrheit machen

1. Tests bei jedem Pull Request automatisch ausführen.
2. Nach Freigabe ein unveränderliches Docker-Image mit Commit-SHA bauen.
3. Produktion nur auf genau dieses Image umschalten.
4. Deployment-Ergebnis und Rollback-Version protokollieren.
5. Secrets ausschließlich auf Server beziehungsweise Deployment-Plattform halten.

So bleibt der Droplet bestehen, aber „Dateien per Hand auf den Server kopieren“ entfällt weitgehend.

### Phase 3: Komfort und Benutzerverwaltung

Das Dashboard kann später vor eine persönliche Anmeldung gestellt werden, beispielsweise mit E-Mail-Einmalcode oder Firmen-Login. Dann gibt es keine gemeinsam geteilten Passwörter mehr. Der Webhook-Pfad bleibt separat maschinell geschützt.

### Phase 4: Managed-Plattform nur bei echtem Anlass

Auf App Platform plus PostgreSQL wechseln, wenn mindestens einer dieser Punkte wichtig wird:

- mehrere parallele App-Instanzen,
- höhere Verfügbarkeitsanforderungen,
- kein eigener Ubuntu-/SSH-Betrieb mehr erwünscht,
- mehrere Integrationen greifen gleichzeitig auf denselben Zustand zu,
- professionelles Rollen-, Audit- und Alarmierungssystem wird benötigt.

## Quellen und technische Grundlage

- [DigitalOcean: Daten in App Platform speichern](https://docs.digitalocean.com/products/app-platform/how-to/store-data/)
- [DigitalOcean: Droplet-Backups](https://docs.digitalocean.com/products/backups/)
- [DigitalOcean: Managed PostgreSQL](https://docs.digitalocean.com/products/databases/postgresql/)
- [DigitalOcean: Deployment über GitHub Actions](https://docs.digitalocean.com/products/app-platform/how-to/deploy-from-github-actions/)
- [Caddy: Automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Anny: Webhooks](https://docs.anny.co/en/articles/349740-webhooks)

