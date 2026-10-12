import type { AnalyticsExecution } from "@/types/api/analytics";

export function executionStatus(execution: AnalyticsExecution): string {
  if (execution.liveness_status === "heartbeat_expired") return "Heartbeat overdue";
  if (!execution.outcome && execution.liveness_status === "untracked") return "Status unknown";
  return execution.outcome ?? "In flight";
}
