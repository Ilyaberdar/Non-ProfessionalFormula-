# Non-ProfessionalFormula-

## Auto Deploy

This repo includes two deploy approaches:

- `GitHub Actions self-hosted runner`
- `GitHub webhook listener`

Files:

- `docker-compose.yml`
- `deploy/deploy.sh`
- `deploy/redeploy.sh`
- `deploy/github_webhook_listener.py`
- `deploy/non-professional-formula-webhook.service`
- `deploy/webhook.env.example`
- `.github/workflows/deploy.yml`

### Recommended for home server without public IP

Use `GitHub Actions self-hosted runner`.

Flow:

- GitHub sees a push to `main`.
- The workflow in `.github/workflows/deploy.yml` runs on your home server runner.
- The runner executes `deploy/redeploy.sh`.
- The script rebuilds and restarts the Docker containers with `docker compose up -d --build --remove-orphans`.

Typical setup:

1. Install Docker and Docker Compose plugin on the server.
2. Clone this repo to the server.
3. Put production `.env` in the repo root.
4. Make the redeploy script executable:
   `chmod +x deploy/redeploy.sh`
5. In GitHub:
   `Repo -> Settings -> Actions -> Runners -> New self-hosted runner`
6. Follow GitHub's runner install commands on the server inside the repo or a dedicated runner directory.
7. Start the runner service.
8. Push to `main`.

Useful commands:

- `tail -f deploy/deploy.log`
- `docker compose ps`
- `docker compose logs -f`

### Alternative for server with public IP

Use the webhook listener.

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
