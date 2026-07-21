import { Suspense } from "react";

import { LoadingState } from "@/components/dashboard/LoadingState";
import { ExplorePageClient } from "./ExplorePageClient";

export default function ExplorePage() {
  return (
    <Suspense fallback={<LoadingState label="Loading season route" />}>
      <ExplorePageClient />
    </Suspense>
  );
}
