/** @type {import('next').NextConfig} */
// The Content-Security-Policy and X-Frame-Options are NOT set here. They carry a per-request
// script nonce, which a static `headers()` table cannot express, so `proxy.ts` owns them and
// builds them from `lib/csp.mjs`. Setting the policy in both places would hand the browser two
// policies to intersect, and the stricter one wins on every directive, which would reinstate the
// nonce-less `script-src` that leaves this console rendering as dead markup.
//
// What IS here is the refusal: `next build` and `next start` both evaluate this file at module
// scope, so a layout that has lost its `force-dynamic` (and therefore cannot carry the nonce)
// fails the build instead of shipping a console whose controls silently do nothing.
import { readFileSync } from "node:fs";

import { assertHydratableCsp } from "./lib/csp.mjs";

assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

// NEXT_PUBLIC_BASE_PATH mounts the UI (and its assets) under a reverse-proxy sub-path
// (e.g. /agent) for same-origin embedding; blank keeps standalone behavior unchanged.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  agentRules: false,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
