import http from "k6/http";
import { check, sleep } from "k6";
import encoding from "k6/encoding";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const ADMIN_USER = __ENV.ADMIN_USER;
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD;
const ADMIN_AUTH_HEADER = __ENV.ADMIN_AUTH_HEADER;

function authHeaders() {
  if (ADMIN_AUTH_HEADER) {
    return { Authorization: ADMIN_AUTH_HEADER };
  }
  if (!ADMIN_USER || !ADMIN_PASSWORD) {
    throw new Error("Set ADMIN_USER/ADMIN_PASSWORD or ADMIN_AUTH_HEADER for admin requests.");
  }
  const token = encoding.b64encode(`${ADMIN_USER}:${ADMIN_PASSWORD}`);
  return { Authorization: `Basic ${token}` };
}

export const options = {
  vus: 1,
  duration: "45s",
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<800"],
  },
};

const adminEndpoints = [
  "/v1/admin/whoami",
  "/v1/admin/profile",
  "/v1/admin/jobs/status",
];

export default function () {
  const headers = { headers: authHeaders() };
  for (const path of adminEndpoints) {
    const res = http.get(`${BASE_URL}${path}`, { ...headers, tags: { name: path } });
    check(res, {
      "admin status 200": (r) => r.status === 200,
    });
  }

  sleep(1);
}
