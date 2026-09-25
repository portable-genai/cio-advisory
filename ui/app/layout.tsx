import type { Metadata } from "next";

import { ModelPills } from "../components/ModelPills";
import "./globals.css";

export const metadata: Metadata = {
  title: "CIO Advisory Assistant",
  description:
    "Grounded, suitability-checked decision-support talking points for private-bank relationship managers. Decision-support, not financial advice.",
};

// Required by the nonce-based CSP in `lib/csp.mjs`, not a performance preference. Next can only
// stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route; a statically
// prerendered page was built before the nonce existed, so every script tag ships bare, and
// `'strict-dynamic'` has switched off the `'self'` fallback that was at least loading the chunks.
// The browser then blocks strictly MORE than it did before the nonce was added, and the console
// renders as dead markup. `assertHydratableCsp` fails the build if this line is removed, and
// `scripts/assert-hydratable.mjs` fails the ui gate if the served HTML disagrees anyway.
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // EMBED mode (NEXT_PUBLIC_EMBED=1): the host page owns the chrome, so render the
  // console bare (no standalone body sizing; ClientPanel also drops its brand header)
  // and let the host's layout wrap it.
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  // The model pills render in BOTH modes, and embedded is the mode that needs them most: a
  // panel inside somebody else's portal is where a viewer has least context about which model
  // answered. They are mounted in the layout rather than in a page because "at the top of
  // every page" is a property of the console, and a page that forgot them would be the one
  // page a screenshot came from.
  return (
    <html lang="en">
      <body className={embed ? undefined : "min-h-screen"}>
        <ModelPills />
        {children}
      </body>
    </html>
  );
}
