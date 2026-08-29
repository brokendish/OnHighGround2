# Installation

This is the canonical installation guide for the public OnHighGround2
configuration. README provides orientation only; do not use older guides as a
second installation procedure.

## Supported execution model and prerequisites

The documented deployment model is Docker Compose on a Linux Docker host.
Docker Desktop on macOS is an expected development path, but it has not been
validated as a clean-install release target. Docker Desktop filesystem and file
ownership behaviour can differ from Linux.

The Compose configuration includes OSRM services declared for `linux/amd64`.
Native arm64 operation, Windows-native deployment, non-Docker deployment, and
Kubernetes deployment are not validated by this guide. No minimum Docker or
Compose version has been established; install a current Docker Engine or Docker
Desktop with the Compose v2 plugin and use the `docker compose` command.

Install or provide:

- Git, to obtain the repository
- Docker Engine or Docker Desktop
- Docker Compose v2 (`docker compose version`)
- A supported web browser for the public UI

Full geographic-data preparation and OSRM preprocessing can require substantial
disk, memory, and CPU. Exact host-resource minimums are not established. The
data-less public smoke path below does not represent a full-data deployment.

## 1. Clone and prepare public configuration

```bash
git clone https://github.com/brokendish/OnHighGround2.git
cd OnHighGround2
cp backend/.env.example .env
```

`.env` is optional to Compose but is the public configuration file when values
are needed. It is local-only: do not commit it. See
[Configuration](configuration.md) before adding API keys or other values.

Do not create `.env.operator` for the public-core path. The operator is an
optional privileged component with a separate procedure in
[Operator setup](operator-setup.md).

## 2. Prepare the runtime directory

The public service reads deployed runtime data. Prepare the runtime directory
with the existing publish script:

```bash
scripts/publish/deploy_to_runtime.sh --region tokyo --dry-run
scripts/publish/deploy_to_runtime.sh --region tokyo
```

With no geographic data prepared, the application may start in a degraded state.
That is useful for smoke verification only; elevation, hazard, routing, and map
content will not be complete. Follow [Data setup](data-setup.md) for the
canonical dataset inventory, acquisition, preparation, and atomic publish flow.

## 3. Start the public-core smoke path

```bash
docker compose build backend-public
docker compose up -d backend-public frontend
```

`runtime-init` is started automatically before `backend-public`. The command
does not start the optional operator or streamer profiles.

Verify the public endpoint:

```bash
curl -fsS http://localhost:8080/health
```

Open <http://localhost:8080/> in a browser. `ok` or `degraded` is an expected
health status depending on available data.

## 4. Prepared-data components

After the required geographic data and generated artifacts are available, start
the needed components explicitly:

```bash
docker compose up -d osrm-walking backend-public frontend martin
docker compose --profile driving up -d osrm-driving
```

OSRM requires the corresponding prepared PBF and derived artifacts. Martin
requires prepared tile data. These are not optional merely because the service
container starts; use them only after completing the future full data guide.

For local development that needs direct loopback access to OSRM or Martin, use
the explicit development override, never the default deployment command:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d martin
```

## 5. Optional components

Do not add either of these to the public-core first-start command:

- **Operator:** privileged and disabled by default. Read
  [Operator setup](operator-setup.md).
- **Streamer:** optional, resource-intensive, requires separate configuration
  and secrets, and is enabled only with `--profile streamer`.

Playwright/npm are development and test dependencies, not public-runtime
prerequisites.

## Stop services

```bash
docker compose down
```

This removes containers and networks while keeping named volumes. Do not use
`docker compose down -v` as routine shutdown: it deletes named volumes and can
remove locally retained state.

## Common first checks

| Symptom | Check |
| --- | --- |
| `frontend` is not reachable | Run `docker compose ps`, then inspect `docker compose logs frontend`. |
| Health is `degraded` | Confirm that runtime data was deployed; full data preparation is still required. |
| OSRM exits | Confirm its required prepared PBF/artifacts exist before starting it. |
| A public `/admin` URL is unavailable | Expected. Operator access follows [Operator setup](operator-setup.md). |

Next: review [Configuration](configuration.md), then use
[Operator setup](operator-setup.md) only when privileged administration is
actually required.
