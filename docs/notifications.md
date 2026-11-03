# Notifications

Your van can message your phone when something needs attention. Everything is
set up in the dashboard under **Alerts**: a guide walks you through it in about
three minutes.

## Apps

| | ntfy (recommended) | Telegram |
|---|---|---|
| Cost | free | free |
| Account | none | your Telegram account |
| Setup | install the app, subscribe to your van's topic | create a bot with @BotFather, send it one message |

WhatsApp and SMS are not offered: WhatsApp only allows automatic messages
through a paid business account, and SMS needs a SIM card and modem in the van.

**ntfy topic**: the van gets a random topic like `kombi-k7m2-q9xr-4tnp-wd3h`.
Whoever knows it can read the messages, so don't share it. **Alerts → ntfy →
New topic** makes a new one. You can use your own ntfy server instead of
ntfy.sh (the guide's advanced options).

**Telegram bot token**: stays on the Pi, is never shown again and never sent to
the remote dashboard.

## Alerts

| Alert | When | Day & night |
|---|---|---|
| Battery low | state of charge below the limit (default 20 %) | |
| Battery forecast | usage + sun forecast say the battery gets below the limit within 36 h | |
| Not charging while driving | driving 10 min, battery current not positive | |
| Cold inside | below the limit (default 3 °C) | ✓ |
| Hot inside | above the limit (default 35 °C, off by default) | ✓ |
| Frost tonight | in the late afternoon, forecast at or below 0 °C overnight | |
| Water almost empty | below 10 % | |
| The van is moving (theft) | it drives off after standing still ≥ 30 min | ✓ |
| Something stopped working | a temperature sensor, the GPS or a Victron device stops reporting | |
| Safety cutoff | a relay was switched off because it got too hot | ✓ |

An alert is sent once, when the problem starts (after a short check that it
isn't a single odd reading), and again only after it has cleared, unless you
ask for reminders. Limits have a margin: "battery below 20 %" clears above 25 %.
A restart does not send active alerts again.

**Quiet hours** (default 22:00-07:00) hold the other messages until the morning.

## Theft alert

There is nothing to switch on when you leave the van. When it starts driving
after standing still, you get an urgent message with a map link. If it's you,
ignore it, or tap **I'm driving, pause** before leaving. You can also limit it
to night-time.

The van needs its own internet to warn you while you're away. If its internet
is your phone's hotspot, that leaves with you. A small 4G router with a SIM card
in the van solves this.

## Without internet

Messages wait in the van and are sent as soon as it is online again (with a
note that they are late). Anything older than 24 hours is dropped. Every
message is listed under **Alerts → Recent notifications** either way.
