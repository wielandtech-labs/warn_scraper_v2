import { lazy } from "react";

/* Peek bodies, code-split: tables on eagerly loaded routes reference these,
   and the bodies (plus StateSilhouette, Sparkline, stateGeometry) would
   otherwise ride in the entry chunk for a card most visitors never open.
   <Peek> supplies the Suspense boundary. */
export const StatePeek = lazy(() =>
  import("./PeekContent").then((m) => ({ default: m.StatePeek })),
);
export const CompanyPeek = lazy(() =>
  import("./PeekContent").then((m) => ({ default: m.CompanyPeek })),
);
