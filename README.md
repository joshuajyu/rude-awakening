# rude-awakening

When Rootly pages you, this makes a Google Nest Mini blare an alarm at high
volume until you stop it. Your phone can sleep in another room.

```
Rootly ──SMS──▶ iPhone Shortcuts automation (only fires when you're home)
                  │ HTTPS POST /page + X-Webhook-Token
                  ▼
           Cloudflare Tunnel ──▶ cloudflared on the Wyse
                                   │
                     http://127.0.0.1:8080  (webhook service)
                                   │ pychromecast
                                   ▼
     Nest Mini ──fetches──▶ http://10.0.0.2:8081/alarm.mp3
```

Rootly doesn't call the webhook directly, because that needs Rootly admin
rights to set up a workflow. Instead, Rootly texts your iPhone as it
normally would, and a Shortcuts automation forwards the page to the
webhook.

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

The repo is private. The Wyse reads it with a **read-only deploy key**, an
SSH key that can only read this repo, so no GitHub account credentials (and
no `gh`) are needed on the server:

```bash
sudo apt-get install -y git python3-venv
ssh-keygen -t ed25519 -N "" -C "wyse rude-awakening deploy key" -f ~/.ssh/rude_awakening_deploy
cat >> ~/.ssh/config <<'EOF'
Host github-rude-awakening
    HostName github.com
    User git
    IdentityFile ~/.ssh/rude_awakening_deploy
    IdentitiesOnly yes
EOF
cat ~/.ssh/rude_awakening_deploy.pub
```

Add that public key under the repo's **Settings → Deploy keys** with write
access left off. Or, from a machine where `gh` is logged in, run
`gh repo deploy-key add rude_awakening_deploy.pub --repo joshuajyu/rude-awakening`.
Then:

```bash
git clone git@github-rude-awakening:joshuajyu/rude-awakening.git ~/rude-awakening
cd ~/rude-awakening
./install.sh
```

On first connect, SSH asks you to trust GitHub's host key. The ED25519
fingerprint should be `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`.

To update later, run `git pull && ./install.sh`. `install.sh` is safe to
rerun. It:

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

## 3. iPhone automation

### Get pages by SMS

Shortcuts can react to text messages but not to push notifications from
other apps. In Rootly, open your **personal notification rules** and make
sure SMS is one of the methods for a page. Save the number Rootly texts
from as a contact called **Rootly**.

### Get the token onto the phone

Get the token from the Wyse onto your Mac's clipboard without printing it:

```bash
ssh joshuayu@10.0.0.2 "grep '^WEBHOOK_TOKEN=' ~/rude-awakening/.env | cut -d= -f2-" | tr -d '\n' | pbcopy
```

Then paste it on the iPhone via Universal Clipboard (same Apple ID, with
Handoff on). The token is 43 characters: letters, numbers, `-` and `_`.
Make sure nothing else comes along with it. A stray line break or other
invisible character makes Cloudflare reject the request with a
`400 Bad Request`, which never shows up in the service's logs.

### Build the automation

In the **Shortcuts** app, go to **Automation → + → Message**:

- **Sender:** Rootly
- **Run Immediately**, with **Notify When Run** off

Then build these actions. Set the URL to `/test` while you set it up, and
change it to `/page` in **both** places once it works.

```
Get Network Details  (Wi-Fi → Network Name)
If  Network Details  is  <home Wi-Fi name>
    Get Contents of URL   ← request below
Otherwise
    Get Current Location
    Get Details of Locations  (Postal Code)
    If  Postal Code  begins with  <first 3 characters of home postal code>
        Get Contents of URL   ← request below
    End If
End If
```

The request, in both places:

- **URL:** `https://page.example.com/page`. Use lowercase with no trailing
  slash; the tunnel's path filter returns 404 for anything else.
- **Method:** `POST`
- **Headers:** `X-Webhook-Token` = the token
- **Request Body:** JSON, with key `title` = *Shortcut Input*. This puts the
  SMS text in the service's logs.

Why the two checks: the alarm shouldn't wake the rest of the house when you
aren't home.
- **Home Wi-Fi** decides most of the time.
- **Location** catches the case where your phone is on cellular at home.
  It checks only the first three characters of the postal code because the
  phone's location is approximate and often reports a neighbour's full
  postal code. The catch is that a page while you're on cellular somewhere
  in the same area also rings the Nest at home.

Before the first automated run, tap ▶ in the editor once with Wi-Fi off and
allow location access. An automation that runs immediately can't show the
permission prompt, so Get Current Location would fail with no error shown.

### Keep it working

- Leave the phone plugged in, somewhere with good Wi-Fi.
- Let Rootly's SMS through your Sleep or Do Not Disturb focus.
- To stop the alarm, say "Hey Google, stop" or tap the Nest. Otherwise it
  stops itself after 10 minutes. Repeat SMS for the same page are ignored
  while it's ringing.

> **Keep a fallback escalation.** This depends on your phone, home Wi-Fi or
> signal, your internet, Cloudflare, the Wyse and the Nest all working, and
> with the phone in another room you won't hear it if any of them fails.
> Keep a later escalation level in Rootly (a backup responder, or a phone
> call after a few minutes), so a page still reaches someone if this chain
> is down.

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

Then test the phone, with the automation's URLs still on `/test`. Watch
`journalctl -u rude-awakening -f` on the Wyse and send yourself a test
notification from Rootly, twice:

1. **On home Wi-Fi.** You should see `Test received: ... title='<the SMS text>'`,
   then `Nest is playing the alarm`.
2. **With Wi-Fi off** (cellular), still at home. The location check should
   match, and you should see the same lines.

If nothing shows up in the logs, the request didn't reach the Wyse. Add a
**Show Content** action after Get Contents of URL and run the automation
by hand to see the reply:

| Reply | Cause |
|-------|-------|
| `{"status": "testing"}` | It works. If it fails only when triggered by SMS, check the trigger and location permission. |
| `{"detail": "invalid token"}` | The header name or token value is wrong. |
| `400 Bad Request` (from Cloudflare) | An invisible character in the token value. Delete the value and paste it again. |
| 404 | The URL path isn't exactly `/test` or `/page`. |
| Nothing (location branch) | The postal code didn't match. Show *Postal Code* to see what the phone reports. |

When both tests pass, switch both URLs to `/page`.

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
