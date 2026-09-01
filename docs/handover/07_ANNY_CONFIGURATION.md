# 07 – Anny Configuration

Stand der UI- und Integrationsprüfung: 1. September 2026

## Rolle von Anny

Anny ist das führende Buchungssystem. Der Allocator vertraut dem Webhook nur für Ereignistyp und Buchungs-ID und lädt die aktuelle Buchung anschließend erneut über die API. Kundendaten und Orders werden für die Zuweisung nicht benötigt.

## Verifizierte Organisation und Ressource

| Merkmal | Stand |
| --- | --- |
| sichtbare Organisation | Volta Pong |
| eingeloggter Benutzer beim Audit | Philipp Langer |
| Benutzerrolle/Org-Owner/MFA | TODO – vor finaler Übergabe verifizieren |
| relevante Ressource | `181227`, „Ping Pong Tisch“ |
| API-Basis | `https://b.anny.co/api/v1` |
| fachliche Zeitzone | `Europe/Zurich` |

## API Credential

Der aktive Produktions-Token „Volta Pong Tischzuweisung v3“ war beim Audit aktiv und besitzt genau:

- `b.bookings:read`
- `b.bookings:update`

Er wurde am 1. September 2026 erstellt und läuft nach der sichtbaren Einstellung am 1. September 2027 ab. Der Wert wird weder hier noch sonst in Git dokumentiert.

Zusätzlich existiert noch der alte Token „annyAPI“ mit sehr breiten Rechten (`b.*` und viele weitere Scopes). Er ist nachweislich noch aktiv, wird aber nicht mehr vom Server verwendet. Er soll nach Abschluss der Übergabe-/Regressionstests widerrufen werden.

**HIGH PRIORITY:** Alt-Token widerrufen und neuen Produktionstoken rechtzeitig vor Ablauf rotieren. Token-Owner und Ablaufalarm müssen organisatorisch zugewiesen werden.

## Webhook

Verifizierte Konfiguration:

| Feld | Wert |
| --- | --- |
| Name | `webhook_anny` |
| Status | aktiv |
| URL | `https://webhook.voltabreau.ch/?key=<WEBHOOK_SECRET>` |
| Events | `bookings.created`, `bookings.updated`, `bookings.deleted` |
| Restriction | Ressource `181227` („Ping Pong Tisch“) |

`<WEBHOOK_SECRET>` ist ausschließlich ein Platzhalter. Die echte URL niemals in Dokumentation, Tickets oder Screenshots kopieren.

Die Anny-Oberfläche zeigte beim Audit einen kumulierten Fehlerzähler von 1; eine kurz zuvor geprüfte Zustellung vom 1. September 2026 um 22:29 Uhr lieferte HTTP 200. Das beweist aktuelle Zustellung, erklärt aber den älteren Fehler nicht.

**TODO – vor finaler Übergabe verifizieren:** Call History prüfen, Ursache/Datum des einen Fehlers dokumentieren und bestätigen, dass kein Muster wiederholter Fehler besteht.

Anny dokumentiert für fehlgeschlagene Webhooks bis zu drei Wiederholungsversuche und eine automatische Deaktivierung nach fünf aufeinanderfolgenden Fehlern. Das offizielle `event_id` wird vom Allocator zur Idempotenz 90 Tage gespeichert.

## Ereignisbehandlung

| Event | Verhalten |
| --- | --- |
| `bookings.created` | Buchung laden und zuweisen oder als `unassigned` markieren |
| `bookings.updated` | Zeitraum/Ressource/Bedarf/Storno erneut bewerten; eigene Patch-Schleife als No-op erkennen |
| `bookings.deleted` | lokale Allocation löschen und überlappende Warteschlange neu versuchen |

Ein Storno kann je nach Anny-Ablauf als `bookings.updated` mit Stornierungsstatus oder als `bookings.deleted` eintreffen. Der produktive Test bestätigte die Update-Variante. Beide sind im Code abgedeckt.

Nicht erforderlich sind `bookings.started`, `bookings.ended`, `bookings.checked-in` und `bookings.checked-out`.

## API-Nutzung

Der Dienst verwendet:

```text
GET   /bookings/<BOOKING_ID>?include=resource,service
PATCH /bookings/<BOOKING_ID>
```

Er liest beziehungsweise bewertet insbesondere:

- Buchungs-ID und -nummer
- `start_date`, `end_date`
- `status` und `canceled_at`
- `weight`
- verknüpfte `resource` und `service`
- bestehende `customer_note`, `note`, `description` für idempotentes Rückschreiben

Er schreibt:

- `customer_note`: `Deine Tische: ...`
- `note`: `Auto-Allocation: ...`
- verwalteten führenden Abschnitt in `description`: `TISCHE: ...`

## Services und Tischbedarf

Der aktuelle Code interpretiert Anny `weight` als Anzahl physischer Tische:

- ganzzahlig 1 bis 8 → entsprechender Bedarf
- fehlend, nicht numerisch, 0, negativ oder größer als 8 → Fallback auf 1

Die Reihenfolge der Tischlabels kommt aus `TABLE_LABELS` und ist produktiv `Tisch 1` bis `Tisch 8`. Die Service-/Weight-Konfiguration in Anny ist daher fachlich genauso kritisch wie der Code.

**TODO – vor finaler Übergabe verifizieren:** vollständige Liste produktiver Services, deren konfiguriertes `weight`, erwarteter Tischbedarf und verantwortlicher Business Owner als eigenes Anny-Inventar exportieren. Diese Liste war im technischen Audit nicht vollständig verfügbar.

## Bekannte Kapazitätsproblematik

Anny kann Kapazität nach Buchungs-/Ressourceneinheiten begrenzen, während der Allocator `weight` als physische Tischanzahl verwendet. Bei gemischten Ein- und Mehrtischservices kann deshalb:

- Anny „8/8“ und keine weitere Verfügbarkeit anzeigen,
- der Allocator weniger als acht Tische konkret zugewiesen haben,
- gleichzeitig eine Mehrtischbuchung wegen fehlender zusammenhängender/Gesamtkapazität `unassigned` bleiben.

Dieser Fall wurde am 7. September 2026 beobachtet. Er ist kein verbliebener Storno-Bug, sondern ein eigenständiger Modellierungsfehler zwischen Anny-Kapazität und physischem Tischbedarf.

**HIGH PRIORITY:** Services/Weights und Anny-Kapazität fachlich neu modellieren oder echte einzelne Tischressourcen verwenden. Bis dahin muss das Dashboard auf `unassigned` geprüft werden; „8/8 in Anny“ ist kein Beweis für acht gültige Tischzuweisungen.

## Neuen API Token erstellen

1. Mit einem organisatorischen Anny-Admin anmelden.
2. Account/Organisation Settings → API → Personal Access Tokens öffnen.
3. Eindeutigen technischen Namen und organisatorischen Owner verwenden.
4. Nur `b.bookings:read` und `b.bookings:update` wählen.
5. Ablaufdatum setzen und Alarm mindestens 30 Tage vorher einrichten.
6. Wert einmalig direkt in den organisatorischen Secret-Manager übernehmen.
7. Token nie in Git, Chat, Ticket, Screenshot oder Shell-Historie einfügen.

Die genaue Anny-Menübezeichnung kann sich ändern; Scopes und Organisation müssen vor dem Speichern geprüft werden.

## API Token rotieren

1. Neuen minimal berechtigten Token wie oben erzeugen.
2. Im Secret-Manager neue Version anlegen; alten Wert vorerst aktiv lassen.
3. Produktions-`.env` sicher aktualisieren: `ANNY_TOKEN=xxx` steht nur als Dokumentationsplatzhalter.
4. Allocator neu erstellen, weil ein bloßer Prozessrestart eine geänderte Compose-`env_file` nicht zuverlässig neu einliest:

   ```bash
   cd /opt/anny_webhook
   docker compose up -d --no-build --no-deps --force-recreate allocator
   ```

5. Health, Logs, kontrollierte Testbuchung und erfolgreichen Anny GET/PATCH prüfen.
6. Erst danach alten Token in Anny widerrufen.
7. Rotation, Owner und neues Ablaufdatum ohne Tokenwert dokumentieren.

Rollback bei Fehlschlag: alten noch aktiven Token aus dem Secret-Manager wieder als Deploymentversion setzen, Container neu erstellen, Ursache prüfen. Nie den überberechtigten historischen Token als stillen Dauerfallback hinterlegen.

## Webhook-Secret rotieren

Der aktuelle Code akzeptiert genau ein aktives Secret. Eine Rotation zwischen Anny-URL und Server ist deshalb nicht atomar und braucht ein kurzes kontrolliertes Wartungsfenster.

1. Starkes zufälliges Secret lokal sicher erzeugen und direkt im Secret-Manager speichern.
2. Aktuellen Health-/Webhookzustand und Backup prüfen.
3. Produktions-`.env` mit `WEBHOOK_SECRET=xxx` als neuem Wert aktualisieren, ohne ihn in Shell-Historie/Logs auszugeben.
4. Allocator neu erstellen.
5. Unmittelbar danach Anny-Webhook-URL auf `?key=<NEUES_SECRET>` ändern.
6. Eindeutige Testbuchung auslösen und Call History HTTP 200 prüfen.
7. Prüfen, dass Uvicorn weiterhin ohne Access-Log läuft und Secret nicht in neuen Logs erscheint.
8. Alten Wert aus allen autorisierten Secret-Stores entfernen; Rotation ohne Wert protokollieren.

Für echte Zero-Downtime-Rotation müsste der Code vorübergehend zwei Secrets akzeptieren oder Anny einen unabhängig verifizierten Signatur-/Headermechanismus bereitstellen. Das ist aktuell nicht implementiert.

## Kontrolliertes Testverfahren

### Standardtest nach Credential-/Releaseänderung

1. Zukünftigen, betrieblich freigegebenen Slot wählen.
2. Gekennzeichnete Buchung auf Ressource 181227 anlegen.
3. Anny Call History: Eventtyp, Zeit und HTTP 200 prüfen.
4. Buchung: `customer_note`, interne Notiz und Beschreibung enthalten dieselbe Tischzuweisung.
5. Dashboard/SQLite: Status `assigned`, keine Kollision.
6. Buchung stornieren.
7. Storno-Webhook und lokale Freigabe prüfen.
8. Testdaten fachlich bereinigen und Ergebnis ohne Kundendaten protokollieren.

### Storno-/Nachverteilungstest

Nur in kontrollierter Umgebung beziehungsweise explizit freigegebenem Produktivslot:

1. acht physische Tische vollständig belegen,
2. zusätzliche Buchung als `unassigned` nachweisen,
3. eine blockierende Buchung stornieren,
4. prüfen, dass die wartende Buchung automatisch einen freigewordenen Tisch erhält,
5. Anny-Notizen, E-Mail, SQLite und Kollisionsfreiheit prüfen.

Dieser Ablauf wurde am 1. September 2026 erfolgreich produktiv bestätigt, muss aber nach wesentlichen Logik-/Anny-Konfigurationsänderungen wiederholt werden.

## Anny-Ownership-Lücken

- **HANDOVER BLOCKER:** Org-Owner, zweiter Admin, MFA, Recovery und Billing nicht verifiziert
- **HIGH PRIORITY:** alter überberechtigter Token noch aktiv
- **HIGH PRIORITY:** Token-Ablaufalarm und zuständiger Empfänger fehlen/nicht verifiziert
- **TODO – vor finaler Übergabe verifizieren:** vollständiges Service-/Weight-/Kapazitätsinventar

Offizielle Referenz: [Anny – Webhooks](https://docs.anny.co/en/articles/349740-webhooks)
