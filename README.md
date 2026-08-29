# OnHighGround2

OnHighGround2 is a map-based evacuation-navigation application for helping
people identify routes to higher and safer locations during tsunami, storm-surge,
and flood risks. It uses open geographic data and self-hosted services rather
than Google map, elevation, or routing services.

## What it provides

- Elevation-aware evacuation destination and route suggestions
- Hazard-layer and hazard-status display
- Emergency-shelter information and map overlays
- Public live-information views, including weather and earthquake information
- A Docker Compose deployment for the public application

## Start here

The canonical installation guide is [docs/installation.md](docs/installation.md).
It documents the supported execution model, prerequisites, public-core startup,
and first verification. `QUICKSTART.md` is only a redirect so that there is one
installation source of truth.

| Need | Document |
| --- | --- |
| Install and start the public core | [Installation](docs/installation.md) |
| Configure public, operator, or streamer environment files | [Configuration](docs/configuration.md) |
| Prepare the canonical public datasets | [Data setup](docs/data-setup.md) |
| Run privileged operator services | [Operator setup](docs/operator-setup.md) |
| Browse the documentation set | [Documentation index](docs/README.md) |
| Security policy and current reporting-contact status | [SECURITY.md](SECURITY.md) |
| License and third-party notices | [LICENSE](LICENSE), [ATTRIBUTIONS.md](ATTRIBUTIONS.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [Third-party inventory](docs/third-party-inventory.md) |

Follow [Data setup](docs/data-setup.md) for OSM, DEM, hazard, OSRM, and
Martin/PostGIS preparation. Do not treat a data-less smoke start as a full-data
deployment.

## Deployment roles

- **Public core:** `backend-public` and `frontend` are the minimal public
  startup path. `runtime-init` runs automatically as their prerequisite.
- **Routing and tiles:** OSRM and Martin require prepared geographic data; they
  are not part of the data-less smoke path.
- **Operator:** optional and privileged. It is disabled by default and has a
  separate entrypoint, network, secret, and setup guide. Public `/admin` is
  intentionally unavailable.
- **Streamer:** optional, resource-intensive, and separately configured. It
  requires its own secrets and the `streamer` Compose profile.
- **Browser tests:** Playwright and npm tooling are development/test tools, not
  runtime requirements.

## Public/operator boundary

The default public Compose path does not start the operator profile. Operator
services must be explicitly enabled with `--profile operator` and are exposed
through a loopback-only gateway. Follow [docs/operator-setup.md](docs/operator-setup.md)
instead of attempting to use public `/admin` paths.

## Security and secrets

Never commit `.env`, `.env.operator`, `.env.stream`, API keys, or operator and
streaming secrets. The example files contain placeholders only; see
[docs/configuration.md](docs/configuration.md) for their roles.

## License and attribution

The project is licensed under the [MIT License](LICENSE). Geographic data,
external APIs, and bundled third-party software have their own terms; consult
[ATTRIBUTIONS.md](ATTRIBUTIONS.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
