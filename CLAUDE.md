# CLAUDE.md

Read [README.md](README.md) first. It covers what this is, how the parts fit
together (Rootly SMS → iPhone Shortcuts → Cloudflare Tunnel → the Wyse →
Nest Mini), setup, configuration and troubleshooting. This file only adds
what you need to work on the repo.

## Layout

- `rude_awakening/app.py`: FastAPI endpoints, token auth, payload summary
- `rude_awakening/alarm.py`: Nest connection, the play/loop/restore logic
  (`Ringer`), and one-alarm-at-a-time handling (`AlarmController`)
- `rude_awakening/media.py`: the LAN-only server that hands the sound to the Nest
- `rude_awakening/config.py`: settings from `.env`, validated at startup
- `install.sh` + `systemd/rude-awakening.service.in`: deployment; must stay
  safe to rerun

## Developing

- Run tests with `.venv/bin/python -m pytest`. The Chromecast is faked, so no
  Nest is needed. Add a test for any change to alarm or endpoint behaviour.
- If `python3 -m venv` fails at its pip bootstrap step (it did inside
  Claude Code's sandbox on the Mac), use
  `uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements-dev.txt`.
- The Wyse runs a newer Python (3.14) than the Mac venv, so rerun the tests
  there after dependency changes.
- Keep it small; this is a single-purpose tool.

## Deploying to the Wyse

- `ssh joshuayu@10.0.0.2` works without a prompt from the Mac. The Wyse
  clones with a read-only deploy key, so push from the Mac and then
  `git pull` on the Wyse.
- **sudo on the Wyse needs a password**, so you can't run `install.sh` or
  `systemctl restart` there yourself. Give the user the exact command,
  e.g. `ssh -t joshuayu@10.0.0.2 'sudo systemctl restart rude-awakening'`.
  The service reads `.env` and the code only at startup, so changes need
  that restart.
- The live config is `~/rude-awakening/.env` on the Wyse, and it differs
  from the defaults (e.g. `ALARM_VOLUME=100`). Change it there, not in
  `.env.example`, unless the default itself should change.
- To check the service without making a sound, use
  `curl -s 'http://127.0.0.1:8080/health?nest=true'` on the Wyse, and
  `journalctl -u rude-awakening`.

## Rules

- **Don't play anything on the Nest without the user asking.** It's in a
  bedroom in a shared home. `/test`, `/page` and the Shortcuts automation
  all make sound.
- The Wyse also runs another service; see "The hardware" in the README.
  Never touch it, its config, or ports 53/80/443. Name it only in that
  README section, nowhere else in the repo.
- The repo is meant to go public eventually. Never commit `.env`, the
  token, the real tunnel hostname (the README uses `page.example.com`),
  the home Wi-Fi name or postal code. Check the diff before every commit.
- If a request never shows up in the service's logs, it was rejected at the
  Cloudflare edge (bad header characters → 400, path filter → 404) or never
  left the phone. See the troubleshooting table in the README.
