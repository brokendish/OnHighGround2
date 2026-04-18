# nginx Proxy Patterns

## Overview

The `frontend` container (nginx:alpine) acts as a reverse proxy for all services.
This document records the proxy patterns in use and the reasoning behind them,
including pitfalls encountered during VPS deployment.

---

## Service Routing Map

| Path prefix | Upstream | Notes |
|---|---|---|
| `/api/` | `backend:8000` | FastAPI, static hostname |
| `/osrm/walking/` | `osrm-walking:5001` | OSRM walking engine |
| `/tiles/` | `martin:3000` | Martin vector tile server |
| `/layers/` | nginx static files | GeoJSON served directly |
| `/hazard/` | nginx static files | Deprecated, kept for compat |
| `/admin/` | nginx static files | Admin UI |

---

## Critical Pattern: Prefix Stripping with proxy_pass

### Rule

When the upstream expects a path **without** the nginx location prefix, use a
**literal hostname** in `proxy_pass` with a **trailing slash**:

```nginx
location /osrm/walking/ {
    proxy_pass http://osrm-walking:5001/;
}
```

nginx replaces the matched prefix (`/osrm/walking/`) with the proxy_pass URI (`/`).

Result: `/osrm/walking/route/v1/...` → upstream receives `/route/v1/...`

### What NOT to do

**Variable in proxy_pass host breaks prefix stripping:**

```nginx
# WRONG — nginx does NOT strip /osrm/walking/ when a variable is used
set $osrm_walking osrm-walking;
proxy_pass http://$osrm_walking:5001/;
# upstream receives /osrm/walking/route/v1/... instead of /route/v1/...
```

**rewrite + variable proxy_pass is also unreliable:**

```nginx
# WRONG — when proxy_pass uses a variable, rewrite results may not apply
rewrite ^/osrm/walking/(.*) /$1 break;
proxy_pass http://$osrm_walking:5001;
```

Both patterns produce `InvalidUrl` errors at the upstream (OSRM returns HTTP 400
with `"URL string malformed close to position 1: \"/\""` when it receives a path
it doesn't recognise).

### When the variable pattern is needed

The variable pattern with `resolver 127.0.0.11` is used when the upstream may
not exist when nginx starts, to avoid nginx failing to resolve the hostname at
startup. In that case, prefix stripping must be done differently:

```nginx
# Pattern for optional/late-starting upstreams (with correct prefix stripping)
location /osrm/walking/ {
    resolver 127.0.0.11 valid=30s ipv6=off;
    set $upstream "http://osrm-walking:5001";
    # Compute stripped path into a variable, then include it in proxy_pass
    # (advanced — only needed if osrm-walking may be absent at nginx start)
}
```

For this project, `osrm-walking` is listed in `depends_on` of the `frontend`
service, so the literal hostname pattern is safe.

---

## OSRM Walking Proxy

```nginx
location /osrm/walking/ {
    proxy_pass http://osrm-walking:5001/;
    proxy_set_header Host $host;
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET, OPTIONS' always;
    if ($request_method = 'OPTIONS') { return 204; }
}
```

The frontend JavaScript sends requests to `/osrm/walking/route/v1/{profile}/...`.
OSRM expects `/route/v1/{profile}/...`. The trailing slash in `proxy_pass`
performs the substitution automatically.

The `profile` string in the URL (`walking`, `foot`, etc.) is not validated by
OSRM at the API level — the routing profile is determined at index build time
(`osrm-extract -p /opt/foot.lua`).

---

## osrm-driving: Optional Profile

`osrm-driving` is declared with `profiles: ["driving"]` in `docker-compose.yml`.
It does not start by default. The corresponding nginx location block is
commented out (see `nginx.conf`).

To enable driving routing:

```bash
docker compose --profile driving up -d osrm-driving
```

Then restore the nginx location block and reload:

```bash
# In nginx.conf, uncomment:
# location /osrm/driving/ {
#     proxy_pass http://osrm-driving:5000/;
#     ...
# }
docker compose exec frontend nginx -s reload
```
