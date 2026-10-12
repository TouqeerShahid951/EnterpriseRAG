import { createContext, useContext, type ReactNode } from "react";

import type { WorkspaceBranding } from "@/types/api";

export const defaultBranding: WorkspaceBranding = {
  app_name: "Prudentia AI",
  primary_color: "#b8a77a",
  accent_color: "#b8a77a",
  background_color: "#101016",
  login_message: "Use your organization credentials to continue.",
  support_url: null,
  theme_mode: "user",
  h1_size: "standard",
  h1_weight: "bold",
  h1_color: null,
  h2_size: "standard",
  h2_weight: "bold",
  h2_color: null,
  body_size: "standard",
  logo_url: null,
  updated_at: null,
};

const BrandContext = createContext<WorkspaceBranding>(defaultBranding);

export function BrandProvider({ children, value }: { children: ReactNode; value?: WorkspaceBranding }) {
  return <BrandContext.Provider value={value ?? defaultBranding}>{children}</BrandContext.Provider>;
}

export function useBranding(): WorkspaceBranding {
  return useContext(BrandContext);
}
