"use client";

/** Shares the verified API key, and the selected environment, with the portal.
 *
 * SRS 3.1 asks the developer portal for a "sandbox/production environment
 * switch". The environment is a property of the key itself - `sk_sandbox_...`
 * against `sk_live_...` - so switching means choosing which of a partner's keys
 * the portal is acting with, not flipping a display toggle.
 */

import { createContext, useContext } from "react";

export type PortalEnvironment = "sandbox" | "production";

export const PortalContext = createContext<{
  apiKey: string;
  environment: PortalEnvironment;
}>({ apiKey: "", environment: "sandbox" });

export const usePortal = () => useContext(PortalContext);
