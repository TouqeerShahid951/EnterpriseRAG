import { createContext, useContext } from "react";
import type { SourceRevision } from "@/types/query";

export const SourceRevisionContext = createContext<SourceRevision | undefined>(undefined);
export function useSourceRevision() { return useContext(SourceRevisionContext); }
