import { Suspense } from "react";

import SchedulePageClient from "./SchedulePageClient";

export default function SchedulePage() {
  return (
    <Suspense fallback={<div className="schedule-page">Loading schedule…</div>}>
      <SchedulePageClient />
    </Suspense>
  );
}
