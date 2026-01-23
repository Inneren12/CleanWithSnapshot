import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = (__ENV.BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const BOOKING_CAPTCHA_TOKEN = __ENV.BOOKING_CAPTCHA_TOKEN;

function jsonHeaders() {
  return { headers: { "Content-Type": "application/json" } };
}

function formatDate(date) {
  const year = date.getUTCFullYear();
  const month = `${date.getUTCMonth() + 1}`.padStart(2, "0");
  const day = `${date.getUTCDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export const options = {
  vus: 1,
  duration: "60s",
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<1200"],
  },
};

export default function () {
  const estimatePayload = {
    beds: 2,
    baths: 1,
    cleaning_type: "standard",
    heavy_grease: false,
    multi_floor: false,
    frequency: "one_time",
    add_ons: {},
  };

  const estimateRes = http.post(
    `${BASE_URL}/v1/estimate`,
    JSON.stringify(estimatePayload),
    { ...jsonHeaders(), tags: { name: "estimate" } }
  );

  if (!check(estimateRes, { "estimate status 200": (res) => res.status === 200 })) {
    sleep(1);
    return;
  }

  const estimate = estimateRes.json();
  const preferredDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);

  const leadPayload = {
    name: "Load Test User",
    phone: "+15555550199",
    email: "loadtest@example.com",
    postal_code: "94107",
    address: "123 Load Test Lane",
    preferred_dates: [preferredDate.toISOString()],
    structured_inputs: estimatePayload,
    estimate_snapshot: estimate,
  };

  const leadRes = http.post(
    `${BASE_URL}/v1/leads`,
    JSON.stringify(leadPayload),
    { ...jsonHeaders(), tags: { name: "lead" } }
  );

  if (!check(leadRes, { "lead status 201": (res) => res.status === 201 })) {
    sleep(1);
    return;
  }

  const lead = leadRes.json();

  const slotDate = formatDate(preferredDate);
  const slotsRes = http.get(
    `${BASE_URL}/v1/slots?date=${slotDate}&time_on_site_hours=${estimate.time_on_site_hours}&service_type=${estimatePayload.cleaning_type}`,
    { tags: { name: "slots" } }
  );

  if (!check(slotsRes, { "slots status 200": (res) => res.status === 200 })) {
    sleep(1);
    return;
  }

  const slots = slotsRes.json();
  const slot = Array.isArray(slots.slots) && slots.slots.length > 0 ? slots.slots[0] : null;

  if (!check({ value: slot }, { "slot available": (data) => Boolean(data.value) })) {
    sleep(1);
    return;
  }

  const bookingPayload = {
    starts_at: slot,
    time_on_site_hours: estimate.time_on_site_hours,
    lead_id: lead.lead_id,
    service_type: estimatePayload.cleaning_type,
  };

  if (BOOKING_CAPTCHA_TOKEN) {
    bookingPayload.captcha_token = BOOKING_CAPTCHA_TOKEN;
  }

  const bookingRes = http.post(
    `${BASE_URL}/v1/bookings`,
    JSON.stringify(bookingPayload),
    { ...jsonHeaders(), tags: { name: "booking" } }
  );

  check(bookingRes, {
    "booking status 201": (res) => res.status === 201,
  });

  sleep(1);
}
