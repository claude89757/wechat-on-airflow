# ADR 0006: Cloudflare Tunnel for Airflow Ingress

## Status

Accepted

## Context

The Airflow API server was reachable through a directly exposed host port. The
service needs a stable HTTPS hostname without adding another inbound reverse
proxy or opening a separate TLS listener on the host. Airflow also uses a
configured `/airflow` base path, which its private Execution API URL must
preserve.

## Decision

Expose Airflow at `https://airflow.claude89757.cc/airflow` through a locally
managed Cloudflare Tunnel. Run `cloudflared` as an enabled systemd service on
the Airflow host and forward the hostname to `http://127.0.0.1:8080`.

Run the Airflow API server with proxy-header support and bind its published
host port to `127.0.0.1`. Keep `/airflow` in both `AIRFLOW_BASE_URL` and
`AIRFLOW_EXECUTION_API_SERVER_URL`. Store the tunnel account certificate and
tunnel credentials outside Git with root-only permissions.

Production verification checks the systemd service, loopback health endpoint,
public health endpoint, public UI path, and private Execution API route.

## Consequences

- The Airflow origin no longer needs a directly exposed inbound port.
- Cloudflare provides the public DNS and TLS boundary.
- A tunnel outage affects public UI and API access but does not alter the
  scheduler, worker, database, or notification channel boundaries.
- Changing or omitting the `/airflow` prefix can break task startup, so the
  repository treats it as a tested runtime contract.
