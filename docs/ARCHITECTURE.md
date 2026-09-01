# Architektur und fachlicher Ablauf

## Systemgrenze

Anny ist das führende System für Buchung, Kunde, Service, Ressource, Zeitraum und Buchungsgewicht. Der Allocator hält eine abgeleitete SQLite-Sicht darauf, welche physischen Tische für welche Buchung reserviert wurden. Diese Datenbank ist kein Ersatz für Anny und enthält keine eigenständige Kundenverwaltung.

```text
Anny                         Tischzuweisungsdienst
------------------------     --------------------------------------
Buchung wird geändert  --->  Webhook authentifizieren
                              event_id auf Duplikat prüfen
                              Buchung über API erneut laden
                              Zuweisungsvorgang serialisieren
                              Ressourcenfilter anwenden
                              SQLite-Belegungen abgleichen
                              freie Tische bestimmen
Notizen werden ergänzt <---  Ergebnis per PATCH zurückschreiben
                              Zuweisung in SQLite speichern
```

Der Dienst fragt die Buchung immer erneut bei Anny ab. Er vertraut dem Webhook deshalb nur für Ereignistyp und Buchungs-ID, nicht für die vollständigen Buchungsattribute.

Dabei werden ausschließlich die benötigten Beziehungen `resource` und `service` angefordert. Kunden- und Bestelldaten werden nicht geladen; der produktive Token benötigt nur `b.bookings:read` und `b.bookings:update`.

## Ereignisverarbeitung

Der Webhook akzeptiert die [offizielle Anny-Payload](https://docs.anny.co/en/articles/349740-webhooks) und mehrere historische Varianten. Die offizielle `event_id` wird 90 Tage gespeichert und macht wiederholte Zustellungen idempotent.

- `bookings.created`: Zuweisung berechnen oder eine bestehende passende Zuweisung wiederverwenden.
- `bookings.updated`: wie `created`, sofern `HANDLE_UPDATED=1`; Zeitraum, Ressource und Bedarf werden immer mit dem lokalen Stand verglichen. Ein eigener PATCH löst keinen weiteren PATCH aus, wenn alle verwalteten Felder bereits stimmen.
- `bookings.deleted`: den lokalen Datensatz löschen. Laut Anny umfasst dieses Ereignis ausdrücklich Löschung **und Storno**.
- Stornierungsähnliche Statuswerte oder `canceled_at` in einem Update: den lokalen Datensatz ebenfalls löschen.
- Andere Ereignisse: erfolgreich quittieren, aber ignorieren.

Fachliche Kapazitätsprobleme werden mit HTTP 200 quittiert und als `unassigned` sichtbar gemacht. Temporäre Anny-GET-/PATCH-Fehler liefern HTTP 503. Anny versucht fehlgeschlagene Zustellungen laut Dokumentation bis zu dreimal erneut. Ein fehlgeschlagener `event_id`-Eintrag darf deshalb erneut verarbeitet und nach Erfolg überschrieben werden.

## Zuweisungsalgorithmus

### 1. Bedarf

`compute_need(weight)` akzeptiert ganzzahlige Werte von 1 bis zur Anzahl konfigurierter Tische. Jeder fehlende, nicht numerische oder außerhalb dieses Bereichs liegende Wert wird auf einen Tisch normalisiert.

### 2. Zeitüberschneidung

Zwei halboffene Intervalle `[start, end)` überschneiden sich genau dann, wenn:

```text
a_start < b_end UND b_start < a_end
```

Eine Buchung, die exakt beim Ende einer anderen beginnt, kann daher dieselben Tische verwenden.

### 3. Belegungsbild

Berücksichtigt werden lokale Datensätze mit Status `assigned`, passender Ressource und überschneidendem Zeitraum. Historische Datensätze ohne Ressourcen-ID werden aus Kompatibilitätsgründen ebenfalls berücksichtigt.

### 4. Auswahl

Die Reihenfolge in `TABLE_LABELS` ist fachlich relevant:

1. `adjacent`: erste ausreichend große zusammenhängende freie Gruppe.
2. `any_free`: erste ausreichend große Auswahl beliebiger freier Tische; die interne Notiz erhält den Zusatz `(Split)`.
3. `capacity reconciliation`: erscheint die lokale Belegung voll, werden nur dann die überschneidenden Blocker erneut bei Anny geladen. Bestätigte Stornos und API-404-Buchungen werden entfernt; andere API-Fehler bleiben aus Sicherheitsgründen blockierend.
4. Erneute Auswahl mit der bereinigten lokalen Belegung.
5. `unassigned`: reichen die freien Tische weiterhin nicht, werden keine Tische vergeben und Anny erhält einen manuellen Warnhinweis.
6. Gibt Storno, Löschung oder eine echte Änderung Kapazität frei, werden überlappende `unassigned`-Buchungen nach ursprünglichem Eingangszeitpunkt erneut geladen und bis zum konfigurierten Limit neu zugewiesen.

Die Strategie ist deterministisch, aber nicht global optimierend: sie minimiert weder spätere Fragmentierung noch löst sie alle Buchungen eines Tages gemeinsam.

Die bedarfsabhängige Reconciliation schließt gezielt den kritischen Fall, dass Anny nach einem Storno wieder Kapazität freigibt, der entsprechende SQLite-Eintrag wegen eines verpassten Webhooks aber noch einen Tisch blockiert. Die anschließende Nachverteilung schließt zusätzlich den Fall, dass bereits ältere `unassigned`-Buchungen nach frei gewordener Kapazität liegen bleiben. Normale Buchungen mit ausreichend lokaler Kapazität verursachen keine zusätzlichen Blocker-Abfragen. Bei einer Neuberechnung wird die eigene ältere Allocation nicht als Fremdbelegung gewertet.

## Mitarbeiter-Dashboard

`GET /dashboard` zeigt den operativen Zustand ohne Kundennamen oder Kontaktdaten. Die Daten kommen aus `GET /dashboard/data` und werden alle 30 Sekunden aktualisiert. Beide Endpunkte sowie der vollständige `/allocations`-Export sind mit gemeinsamen, separaten Dashboard-Zugangsdaten geschützt.

Die Ampel arbeitet deterministisch:

- Grün: Datenbank enthält Zuweisungen, keine zukünftigen offenen Fälle und keine Tischkollision.
- Gelb: zukünftige `unassigned`-Einträge, ungültige Zeitdaten, ein noch nicht erfolgreich wiederholter Webhook oder eine noch leere Datenbank.
- Rot: zwei zeitlich überschneidende Buchungen derselben Ressource verwenden dasselbe Tischlabel.

Zusätzlich zeigt es den letzten Anny-Webhook, Ereignisse und automatische Nachverteilungen der letzten 24 Stunden sowie noch retry-fähige Zustellfehler. Das Dashboard prüft den SQLite-Zustand. Es behauptet nicht, einen vollständigen Live-Abgleich aller Buchungen mit Anny durchzuführen.

## Rückschreiben nach Anny

Bei einer Zuweisung werden drei Felder gesetzt:

- `customer_note`: `Deine Tische: ...`
- `note`: `Auto-Allocation: ...`, bei verteilter Gruppe ergänzt um `(Split)`
- `description`: der führende verwaltete Abschnitt `TISCHE: ...` wird ersetzt; der anschließende Mitarbeitertext bleibt erhalten

Ein SHA-256-Hash der gewünschten Patch-Felder wird nur nach erfolgreichem PATCH beziehungsweise bestätigtem No-op gespeichert. Scheitert der PATCH einer neuen Zuweisung, wird die neue lokale Tischbelegung auf `unassigned` zurückgerollt und der Webhook als retry-fähig beantwortet. Eine bereits vorher gültige Zuweisung bleibt bei einem reinen Synchronisationsfehler bestehen.

## Datenmodell

Tabelle `allocations`:

| Feld | Zweck |
| --- | --- |
| `booking_id` | Primärschlüssel aus Anny |
| `booking_number` | lesbare Buchungsnummer |
| `resource_id`, `service_id` | Anny-Bezüge |
| `start_date`, `end_date` | ISO-Zeitfenster |
| `need` | berechnete Tischanzahl |
| `tables_csv` | zugewiesene Labels |
| `status` | `assigned` oder `unassigned` |
| `last_patch_hash`, `patched_at` | Metadaten des letzten Rückschreibens |
| `created_at`, `updated_at` | lokale Zeitstempel |

Indizes bestehen auf Zeitfenster und Ressource. Die Datenbank wird beim Import der Anwendung initialisiert und um ältere fehlende Spalten ergänzt.

Tabelle `webhook_events`:

| Feld | Zweck |
| --- | --- |
| `event_id` | offizieller eindeutiger Anny-Ereignisschlüssel |
| `event_type`, `booking_id` | Zuordnung der Zustellung |
| `processed_at` | Zeitpunkt des letzten Verarbeitungsversuchs |
| `outcome_json` | technisches Ergebnis für Idempotenz, Retry und Dashboard |

## Konsistenzgrenzen

- SQLite kennt nur Ereignisse, die den Dienst erreicht und erfolgreich bis zur lokalen Speicherung durchlaufen haben.
- Der Dienst gleicht den gesamten Bestand nicht regelmäßig mit Anny ab. Er prüft überlappende Blocker gezielt, wenn eine neue Zuweisung sonst wegen voller Kapazität scheitern würde.
- Der vollständige Auswahlvorgang ist innerhalb des einen produktiven Uvicorn-Prozesses durch eine reentrante Sperre serialisiert. Mehrere Uvicorn-Worker oder parallele Container sind ohne zusätzliche verteilte Sperre nicht zulässig.
- Die automatische Nachverteilung ist pro freiem Zeitfenster begrenzt (`REDISTRIBUTION_LIMIT`, Standard 20), damit ein Anny-Ausfall nicht zu unbeschränkt langen Webhook-Anfragen führt.
- Anny bietet optional einen `Signature`-Header an, dokumentiert öffentlich aber keinen verifizierbaren Signaturalgorithmus. Bis dieser mit Anny geklärt und getestet ist, bleibt das vorhandene Webhook-Secret erforderlich.
- Ein kontrollierter vollständiger Bestandsabgleich bleibt eine spätere Ergänzung; Dashboard und Event-Reconciliation ersetzen keinen periodischen Audit.

Diese Grenzen bestimmen die priorisierten nächsten Arbeitspakete in [CURRENT_STATE.md](CURRENT_STATE.md).
