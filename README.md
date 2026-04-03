# Non-ProfessionalFormula-

## Auto Deploy

This repo includes a simple auto-deploy flow for a home server:

- GitHub webhook hits a small Python listener on the server.
- The listener verifies the webhook secret.
- On push to the configured branch, it runs `deploy/deploy.sh`.
- The deploy script does `git fetch`, `git pull --ff-only`, then `docker compose up -d --build --remove-orphans`.

Files:

- `docker-compose.yml`
- `deploy/deploy.sh`
- `deploy/github_webhook_listener.py`
- `deploy/non-professional-formula-webhook.service`
- `deploy/webhook.env.example`

Typical server setup:

1. Clone the repo to `/opt/non-professional-formula`.
2. Put production `.env` in `/opt/non-professional-formula/.env`.
3. Copy `deploy/webhook.env.example` to `deploy/webhook.env` and fill in `WEBHOOK_SECRET`.
4. Make the deploy script executable: `chmod +x deploy/deploy.sh`.
5. Install the systemd unit:
   `sudo cp deploy/non-professional-formula-webhook.service /etc/systemd/system/`
6. Enable and start it:
   `sudo systemctl daemon-reload && sudo systemctl enable --now non-professional-formula-webhook`
7. In GitHub, add a webhook pointing to:
   `http://YOUR_SERVER_IP:9000/github-webhook`
   with content type `application/json`, event `Just the push event`, and the same secret as `WEBHOOK_SECRET`.

Useful commands:

- `sudo systemctl status non-professional-formula-webhook`
- `journalctl -u non-professional-formula-webhook -f`
- `tail -f /opt/non-professional-formula/deploy/deploy.log`
- `docker compose ps`
- `docker compose logs -f`
