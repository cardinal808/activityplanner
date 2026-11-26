# Activiteitenformulier (zelf gehost)

Webapp voor het dagelijkse activiteitenformulier van Meander Medisch Centrum. Je vult het in per blok, met favorieten. Garmin-gegevens (slaap, activiteiten, Body Battery, hartslag) worden elk uur opgehaald, en de app maakt een PDF op het originele formulier.

## 1. LXC aanmaken (Proxmox)

- Template: **Debian 12** (standaard), unprivileged.
- 1 core, 512 MB RAM, 4 GB schijf, netwerk via DHCP of een vast adres.
- Start de container en log in als root (console of `pct enter <id>`).

## 2. Installeren

In de container:

```sh
apt-get update && apt-get install -y git
git clone https://github.com/cardinal808/activityplanner.git /root/activityplanner
cd /root/activityplanner && ./install.sh
```

Bijwerken later: `cd /root/activityplanner && git pull && ./install.sh`. Je data en `/etc/activiteiten.env` blijven bewaard.

## 3. Instellen

Open `http://<ip-van-de-container>:8080`, ga naar **Instellingen → Garmin-koppeling** en plak je persoonlijke API-sleutel. Die maak je in Garmin Connect Web via Personal API Key → Create Key; kies eerst 30 dagen om te testen. De app test de sleutel bij Garmin en bewaart hem alleen als hij werkt, in `/var/lib/activiteiten/garmin-api-key`, leesbaar voor alleen de service. Daarna haalt de app meteen de afgelopen week op. Meer geschiedenis haal je op met "Geschiedenis ophalen".

Zet daarnaast een wachtwoord voor de webpagina in `/etc/activiteiten.env` (`APP_PASSWORD`, gebruiker `APP_USER`) en herstart met `systemctl restart activiteiten`. Zonder wachtwoord kan iedereen op je netwerk je gegevens zien en de sleutel vervangen. Uitlezen kan niemand: de sleutel wordt nooit teruggestuurd.

De sleutel in `/etc/activiteiten.env` zetten (`GARMIN_API_KEY`) kan nog steeds. Een sleutel die je in de interface invult gaat daarvoor.

Technische test van de koppeling. Die toont alleen welke velden Garmin teruggeeft, geen waarden:

```sh
cd /opt/activiteiten && sudo -u activiteiten sh -c 'set -a; . /etc/activiteiten.env; venv/bin/python -m app.sync test'
```

## 4. Gebruiken

Open `http://<ip-van-de-container>:8080`. Op je telefoon kun je de pagina toevoegen aan je beginscherm.

- **Dag**: tik op een leeg vakje of op "+ Blok invullen". Garmin-voorstellen staan grijs met een vraagteken. Met "lege vakjes voorinvullen" neem je ze in één keer over; moeheid en pijn vul je zelf aan. Rechts staat Body Battery per half uur.
- **Formulier**: PDF, afbeelding of afdrukken, op het originele formulier.
- **Trends**: moeheid en pijn naast Body Battery, slaap, stappen en stress.
- **Instellingen**: naam, favorieten, CSV-export en import van de claude.ai-versie.

## Bereikbaarheid

Thuis via je lokale netwerk. Onderweg het liefst via **Tailscale** (installeer het in de container, of gebruik je bestaande subnet-router). Zet poort 8080 niet zonder `APP_PASSWORD` en HTTPS open naar internet: dit zijn gezondheidsgegevens. Gebruik je al een reverse proxy, zoals Nginx Proxy Manager of Caddy, zet de app daar dan achter, met HTTPS.

## Beheer

| Wat | Commando |
|---|---|
| Status | `systemctl status activiteiten activiteiten-garmin.timer` |
| Logs | `journalctl -u activiteiten -u activiteiten-garmin -n 50` |
| Nu Garmin ophalen | `systemctl start activiteiten-garmin` |
| Bijwerken | `cd /root/activityplanner && git pull && ./install.sh` (data en instellingen blijven) |
| Back-up | `/var/lib/activiteiten/activiteiten.db` (of een Proxmox-back-up van de container) |

## Goed om te weten

- Garmin levert stappen alleen als dagtotaal, niet per kwartier. "Staan/lopen" wordt daarom alleen voorgesteld voor activiteiten die je op je horloge hebt opgenomen, zoals een wandeling. "Liggen" komt uit slaap en dutjes.
- Een persoonlijke API-sleutel verloopt (30 dagen tot 1 jaar). Garmin mailt je vooraf; plak de nieuwe sleutel bij Instellingen. Bij Instellingen zie je ook wanneer er voor het laatst is opgehaald, en of dat lukte.
- Garmin begrenst het aantal verzoeken (HTTP 429). De app wacht dan even en gaat de volgende keer verder: elk uur haalt de timer een stuk van de gevraagde geschiedenis op, tot alles binnen is. Een dag met fouten overschrijft nooit eerder opgehaalde, betere gegevens.
- De Garmin-endpoints komen uit Garmins Personal API-documentatie (versie 1.0.0). Werkt een onderdeel niet, dan staat dat in de log en blijft de rest gewoon werken.
