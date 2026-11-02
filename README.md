# rude-awakening

When Rootly pages you, this makes a Google Nest Mini blare an alarm at high
volume until you stop it.

```
Rootly workflow ──HTTPS──▶ Cloudflare Tunnel ──▶ cloudflared on the Wyse
                                                   │
                                     http://127.0.0.1:8080  (webhook service)
                                                   │ pychromecast
                                                   ▼
                     Nest Mini ──fetches──▶ http://10.0.0.2:8081/alarm.mp3
```

It's a small FastAPI service that runs natively under systemd, alongside
Pi-hole. It doesn't touch Pi-hole or its ports (53/80/443).

| Endpoint      | Auth | What it does |
|---------------|------|--------------|
| `POST /page`  | yes  | Saves the Nest's volume, sets it to `ALARM_VOLUME` (90%), loops the alarm until stopped or `ALARM_TIMEOUT_SECONDS` (10 min), then restores the volume. Ignored if an alarm is already ringing. |
| `POST /stop`  | yes  | Stops the alarm and restores the volume. |
| `POST /test`  | yes  | Plays the alarm for `TEST_DURATION_SECONDS` at `TEST_VOLUME` (40%). A real page takes over from a test. |
| `GET /health` | no   | `{"status": "ok", "alarm_active": false}`. Add `?nest=true` to also check that the Nest is reachable. |

Auth means sending the `X-Webhook-Token: <WEBHOOK_TOKEN>` header. The
endpoints accept any request body; the service logs a short summary of it
(its keys and a title, if one is found).

You can also silence the alarm on the speaker itself by saying "Hey Google,
stop" or tapping the Nest Mini. Either way the volume is restored.

## 1. Install on the Wyse

```bash
sudo apt-get install -y git python3-venv
git clone https://github.com/joshuajyu/rude-awakening.git ~/rude-awakening
cd ~/rude-awakening
./install.sh
```

`install.sh` is safe to rerun, for example after a `git pull`. It:

- creates `.venv` and installs the dependencies
- creates `.env` from `.env.example` with a random `WEBHOOK_TOKEN`, if needed
- installs `/etc/systemd/system/rude-awakening.service`, which runs as your
  user, restarts on failure and starts on boot, then enables it

### Configure the Nest

1. Find the Nest's IP and name. You can get both in the Google Home app
   (device → Settings → Device information), or by asking the network:

   ```bash
   ~/rude-awakening/.venv/bin/python -c "import pychromecast; cs, b = pychromecast.get_chromecasts(); b.stop_discovery(); [print(c.cast_info.friendly_name, c.cast_info.host, c.cast_info.model_name) for c in cs]"
   ```

2. Reserve that IP for the Nest in the Rogers gateway admin page.
3. Edit `~/rude-awakening/.env` and set `NEST_IP` and `NEST_NAME`. The service
   tries the IP first and falls back to discovery by name.
4. Apply the change and check that the service can reach the Nest:

   ```bash
   sudo systemctl restart rude-awakening
   curl -s 'http://127.0.0.1:8080/health?nest=true'
   journalctl -u rude-awakening -f        # logs
   ```

### Ports

| Port | Bound to         | Used for |
|------|------------------|----------|
| 8080 | `127.0.0.1` only | The webhook. Only cloudflared can reach it. |
| 8081 | `10.0.0.2` (LAN) | Serves the alarm file to the Nest. The Nest needs a plain HTTP URL it can reach. Only that one file is served. |

If you've enabled `ufw` (it's off by default on Ubuntu Server), let the Nest
reach the media port:
`sudo ufw allow from 10.0.0.0/24 to any port 8081 proto tcp`.

## 2. Cloudflare Tunnel

This exposes **only** the webhook port. Pi-hole's admin page stays private,
and you don't need any port forwarding on the router.

### Install cloudflared

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
```

### Create the tunnel and route the hostname

These steps use a tunnel managed from the Cloudflare dashboard, which is
simplest:

1. In the Cloudflare dashboard, go to **Zero Trust → Networks → Tunnels →
   Create a tunnel**, choose **Cloudflared**, and name it `rude-awakening`.
2. Under "Install and run a connector", choose Debian. Copy the
   `sudo cloudflared service install <TOKEN>` command and run it on the Wyse.
   This creates and starts the `cloudflared` systemd service, which starts on
   boot.
3. Add a public hostname (the dashboard may call it "Public Hostname" or
   "Published application route"):
   - **Subdomain / domain:** e.g. `page` . `example.com` → `page.example.com`
   - **Path:** `^/(page|stop|test|health)$`. This is optional, but nothing
     else gets through.
   - **Service:** `HTTP` → `127.0.0.1:8080`

   Use `127.0.0.1` rather than `localhost`. `localhost` can resolve to IPv6
   `::1`, and the service only listens on IPv4. Don't add hostnames for
   ports 80 or 443, which are Pi-hole's.
4. Check it from the Wyse:

   ```bash
   systemctl status cloudflared
   curl -s https://page.example.com/health
   ```

<details>
<summary>Alternative: a tunnel managed by a local config file</summary>

```bash
cloudflared tunnel login
cloudflared tunnel create rude-awakening          # prints the tunnel UUID
cloudflared tunnel route dns rude-awakening page.example.com
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/<UUID>.json /etc/cloudflared/
```

Create `/etc/cloudflared/config.yml` with:

```yaml
tunnel: <UUID>
credentials-file: /etc/cloudflared/<UUID>.json
ingress:
  - hostname: page.example.com
    path: ^/(page|stop|test|health)$
    service: http://127.0.0.1:8080
  - service: http_status:404
```

Then run `sudo cloudflared service install`.
</details>

## 3. Rootly workflow

Get the token on the Wyse with `grep WEBHOOK_TOKEN ~/rude-awakening/.env`.

1. In Rootly, go to **Workflows → Create Workflow**. Choose an **Alert**
   workflow triggered when an alert is created, or an **Incident** workflow
   if you page from incidents.
2. Add conditions so it only fires for pages that target you, e.g. your
   escalation policy or your user as the notification target.
3. Add an **HTTP Client** action (search "HTTP" in the action list):
   - **URL:** `https://page.example.com/page`
   - **Method:** `POST`
   - **Headers:**
     ```json
     {"X-Webhook-Token": "<WEBHOOK_TOKEN>", "Content-Type": "application/json"}
     ```
   - **Body:** anything works; the service only logs it. For example:
     ```json
     {"title": "{{ alert.summary }}"}
     ```
     Use whichever Liquid variables Rootly offers in the editor.
   - A successful page returns `202`.
4. Optional: add a second workflow that runs when an alert is
   **acknowledged** and POSTs to `https://page.example.com/stop` with the same
   header. Acknowledging in Rootly will then silence the speaker.

> **Keep a fallback escalation.** This depends on the Wyse, your home
> internet, Cloudflare and the Nest all working. Keep your Rootly personal
> notification rules for push, SMS and phone call, and add a later
> escalation level (a backup responder, or a phone call after a few
> minutes), so a page still reaches someone if this chain is down.

## 4. Test end to end

Work from the inside out:

```bash
# On the Wyse
TOKEN=$(grep '^WEBHOOK_TOKEN=' ~/rude-awakening/.env | cut -d= -f2-)
curl -s 'http://127.0.0.1:8080/health?nest=true'
curl -s -X POST -H "X-Webhook-Token: $TOKEN" http://127.0.0.1:8080/test

# From anywhere (e.g. your Mac or phone hotspot), through the tunnel
curl -s -X POST https://page.example.com/test \
  -H "X-Webhook-Token: $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title": "manual test"}'

# The full alarm, then stop it
curl -s -X POST -H "X-Webhook-Token: $TOKEN" https://page.example.com/page
curl -s -X POST -H "X-Webhook-Token: $TOKEN" https://page.example.com/stop

# A wrong token should return 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'X-Webhook-Token: nope' https://page.example.com/page
```

Finally, trigger a real test page in Rootly (e.g. page yourself) and watch
`journalctl -u rude-awakening -f`. You should see `Page received: ...`
followed by `Ringing at 90% ...`.

## Alarm sound

`sounds/alarm.mp3` is a 10-second beeping pattern generated by
`scripts/make_alarm.py`. It's an original tone with no licensing concerns.
The service replays it until the alarm stops.

To use your own sound, copy any MP3, AAC/M4A, OGG, FLAC or WAV file onto
the Wyse, point `ALARM_FILE` in `.env` at it (absolute, or relative to the
repo), then run `sudo systemctl restart rude-awakening`. The file is read
at startup.

## Configuration

All settings live in `.env`. See [`.env.example`](.env.example) for the full
list and defaults. Never commit `.env`; it's in `.gitignore`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The tests replace the Chromecast with fakes, so you don't need a Nest to
run them.
