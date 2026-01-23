# Tracing backend (Tempo)

This repo ships a Grafana Tempo service in the observability compose stack to provide an OTLP tracing backend and a Grafana datasource.

## Start Tempo + Grafana

```bash
docker compose -f docker-compose.observability.yml up -d tempo grafana
```

Grafana is bound to localhost only at http://127.0.0.1:3001, and the Tempo datasource is pre-provisioned.

## Send traces

From another container on the same Docker network, send OTLP traces to Tempo using one of the internal endpoints:

- OTLP gRPC: `tempo:4317`
- OTLP HTTP: `http://tempo:4318`

Tempo stores trace data on the `tempo_data` volume and is only exposed to other services inside the compose network.
