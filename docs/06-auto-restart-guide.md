# Keeping It Running & Daily Restart (Docker-first)

Updated approach: Docker now owns "keep it running," and `launchd` is only used for calendar-scheduled work. This replaces the earlier 5-agent `launchd` setup with 2–3 agents total.

## 1. "Keep it running" — Docker's `restart: unless-stopped`

This is now handled entirely by the `docker-compose.yml` from the setup guide — every service (`db`, `backend`, `frontend`) has `restart: unless-stopped`, which means:

- **Crash recovery** — if a container dies, Docker restarts it immediately, no polling or `KeepAlive` config needed
- **Reboot recovery** — if the Mac mini restarts, Docker Desktop autostarts at login (enabled in Settings → General) and every container with `unless-stopped` comes back up on its own
- **One log surface** — `docker compose logs -f` instead of tailing scattered `/tmp/*.log` files from separate agents

No `launchd` agents, no wrapper `start-backend.sh`/`start-frontend.sh` scripts, no `exec`/PID tracking concerns — Docker's supervisor replaces all of that.

## 2. Daily restart (optional)

If you still want a clean nightly restart (clears memory buildup, picks up any config changes), it's now a single command instead of a multi-service script:

`~/gridironiq/scripts/restart-all.sh`:
```bash
#!/bin/bash
cd ~/gridironiq
docker compose restart
```
```bash
chmod +x ~/gridironiq/scripts/restart-all.sh
```

`~/Library/LaunchAgents/com.gridironiq.daily-restart.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.gridironiq.daily-restart</string>
  <key>ProgramArguments</key>
  <array><string>/Users/YOUR_USERNAME/gridironiq/scripts/restart-all.sh</string></array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>4</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/gridironiq-restart.log</string>
  <key>StandardErrorPath</key><string>/tmp/gridironiq-restart.err</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gridironiq.daily-restart.plist
```

Test it immediately without waiting for 4am:
```bash
launchctl kickstart -k gui/$(id -u)/com.gridironiq.daily-restart
```

Honestly, with `restart: unless-stopped` already handling crash recovery, this daily restart is a nice-to-have rather than a necessity — skip it entirely if you don't have a specific reason (e.g., a known memory leak) to want one.

## 3. Verify

```bash
docker compose ps
# STATUS column should show "Up" for all three, with restart count visible if any have crashed/recovered

docker compose logs -f
```

To stop everything cleanly (e.g., before editing configs):
```bash
docker compose down
```

---

## Where this fits with the weekly/monthly model pipeline

You now have **3 `launchd` agents max**: the optional daily restart above, plus the weekly retrain and monthly recalibration from the pipeline setup — down from the original 5. Those two pipeline agents stay outside Docker on purpose, since they're calendar-triggered batch jobs, not always-on services; if they ever need to reach Postgres, they connect to `localhost:5432` since the `db` container's port is published to the host.
