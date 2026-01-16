import assert from "node:assert";

import { formatDateKeyInTz } from "../app/admin/lib/timezone";

const cases = [
  {
    iso: "2024-01-01T00:30:00Z",
    timeZone: "UTC",
    expected: "2024-01-01",
  },
  {
    iso: "2024-01-01T05:30:00Z",
    timeZone: "America/Edmonton",
    expected: "2023-12-31",
  },
];

cases.forEach(({ iso, timeZone, expected }) => {
  assert.strictEqual(
    formatDateKeyInTz(iso, timeZone),
    expected,
    `formatDateKeyInTz(${iso}, ${timeZone}) should be ${expected}`,
  );
});

console.log("All timezone date key tests passed.");
