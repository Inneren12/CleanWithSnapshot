import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export const options = {
  vus: 1,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

export default function () {
  const healthz = http.get(`${BASE_URL}/healthz`, { tags: { name: "healthz" } });
  check(healthz, {
    "healthz status 200": (res) => res.status === 200,
  });

  const readyz = http.get(`${BASE_URL}/readyz`, { tags: { name: "readyz" } });
  check(readyz, {
    "readyz status 200": (res) => res.status === 200,
  });

  sleep(1);
}
