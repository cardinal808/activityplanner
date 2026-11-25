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

```sh
nano /etc/activiteiten.env
```

- `GARMIN_API_KEY`: je persoonlijke sleutel. Maak die aan in Garmin Connect Web via Personal API Key → Create Key. Kies eerst 30 dagen om te testen.
- `APP_PASSWORD`: wachtwoord voor de webpagina (gebruiker: `APP_USER`). Sterk aanbevolen.

Herstart daarna de app en test de Garmin-koppeling:

```sh
systemctl restart activiteiten
cd /opt/activiteiten && sudo -u activiteiten sh -c 'set -a; . /etc/activiteiten.env; venv/bin/python -m app.sync test'
```

De test laat alleen zien welke velden Garmin teruggeeft, niet je gezondheidswaarden. Werkt het? Haal dan je geschiedenis op:

```sh
sudo -u activiteiten sh -c 'set -a; . /etc/activiteiten.env; cd /opt/activiteiten; venv/bin/python -m app.sync --days 60'
```

Daarna haalt de timer elk uur vandaag en gisteren op.

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
- Een persoonlijke API-sleutel verloopt (30 dagen tot 1 jaar). Garmin mailt je vooraf; zet de nieuwe sleutel in `/etc/activiteiten.env` en herstart.
- De Garmin-endpoints komen uit Garmins Personal API-documentatie (versie 1.0.0). Werkt een onderdeel niet, dan staat dat in de log en blijft de rest gewoon werken.
