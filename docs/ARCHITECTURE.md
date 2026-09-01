# Architektur und fachlicher Ablauf

## Systemgrenze

Anny ist das führende System für Buchung, Kunde, Service, Ressource, Zeitraum und Buchungsgewicht. Der Allocator hält eine abgeleitete SQLite-Sicht darauf, welche physischen Tische für welche Buchung reserviert wurden. Diese Datenbank ist kein Ersatz für Anny und enthält keine eigenständige Kundenverwaltung.

```text
Anny                         Tischzuweisungsdienst
------------------------     --------------------------------------
Buchung wird geändert  --->  Webhook authentifizieren
                              Buchung über API erneut laden
                              Ressourcenfilter anwenden
                              SQLite-Belegungen abgleichen
                              freie Tische bestimmen
Notizen werden ergänzt <---  Ergebnis per PATCH zurückschreiben
                              Zuweisung in SQLite speichern
```

Der Dienst fragt die Buchung immer erneut bei Anny ab. Er vertraut dem Webhook deshalb nur für Ereignistyp und Buchungs-ID, nicht für die vollständigen Buchungsattribute.

## Ereignisverarbeitung

Der Webhook akzeptiert Ereignis und Buchungs-ID in mehreren historischen Payload-Varianten sowie in den Headern `X-Anny-Event`, `X-Event` oder `X-Webhook-Event`.

- `bookings.created`: Zuweisung berechnen oder eine bestehende passende Zuweisung wiederverwenden.
- `bookings.updated`: wie `created`, sofern `HANDLE_UPDATED=1`; eine als eigene Änderung erkannte Buchung wird zur Schleifenvermeidung übersprungen.
- `bookings.deleted`: den lokalen Datensatz löschen.
- Stornierungsähnliche Statuswerte oder `canceled_at`: den lokalen Datensatz ebenfalls löschen.
- Andere Ereignisse: erfolgreich quittieren, aber ignorieren.

Der HTTP-Status des Webhook bleibt bei fachlichen Fehlern derzeit meist `200`, damit Anny das Ereignis nicht endlos wiederholt. Der JSON-Inhalt muss deshalb im Monitoring ausgewertet werden.

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
3. `unassigned`: reichen alle freien Tische nicht, werden keine Tische vergeben und Anny erhält einen manuellen Warnhinweis.

Die Strategie ist deterministisch, aber nicht global optimierend: sie minimiert weder spätere Fragmentierung noch löst sie alle Buchungen eines Tages gemeinsam.

## Rückschreiben nach Anny

Bei einer Zuweisung werden drei Felder gesetzt:

- `customer_note`: `Deine Tische: ...`
- `note`: `Auto-Allocation: ...`, bei verteilter Gruppe ergänzt um `(Split)`
- `description`: einmalig mit `TISCHE: ...` vorangestellt

Ein SHA-256-Hash der gewünschten Patch-Felder wird lokal gespeichert. Im aktuellen Code wird ein API-Fehler beim PATCH jedoch nicht in einen fehlgeschlagenen Zuweisungsstatus übersetzt; das ist eine bekannte Baustelle.

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

## Konsistenzgrenzen

- SQLite kennt nur Ereignisse, die den Dienst erreicht und erfolgreich bis zur lokalen Speicherung durchlaufen haben.
- Der Dienst gleicht den gesamten Bestand nicht regelmäßig mit Anny ab.
- Mehrere gleichzeitige Webhooks werden nicht durch eine fachliche Transaktion oder verteilte Sperre serialisiert.
- Manuelle Änderungen in Anny können durch den `updated`-Schleifenschutz unbemerkt bleiben.
- `unassigned`-Buchungen werden nicht automatisch erneut versucht, sobald später Tische frei werden.

Diese Grenzen bestimmen die priorisierten nächsten Arbeitspakete in [CURRENT_STATE.md](CURRENT_STATE.md).
