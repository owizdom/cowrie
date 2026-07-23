"use client";

/** Shares the verified API key with the portal's pages. */

import { createContext, useContext } from "react";

export const PortalContext = createContext<{ apiKey: string }>({ apiKey: "" });

export const usePortal = () => useContext(PortalContext);
