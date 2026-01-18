import { Suspense } from "react";

import QualityPhotosClient from "./QualityPhotosClient";

export default function QualityPhotoGalleryPage() {
  return (
    <Suspense
      fallback={
        <div className="admin-page">
          <div className="admin-card admin-section">Loading photos…</div>
        </div>
      }
    >
      <QualityPhotosClient />
    </Suspense>
  );
}
