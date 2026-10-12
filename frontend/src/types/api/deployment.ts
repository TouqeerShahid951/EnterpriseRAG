export interface ResourceSnapshot {
  sampled_at: string;
  gpu?: {
    scope: string;
    unavailable_reason: string | null;
    devices: {
      id: string;
      name: string;
      utilization_percent: number | null;
      memory_used_bytes: number | null;
      memory_total_bytes: number | null;
      temperature_c: number | null;
      power_watts: number | null;
    }[];
  };
  metrics: {
    label: string;
    scope: string;
    percent: number | null;
    used_bytes: number | null;
    total_bytes: number | null;
    unavailable_reason: string | null;
  }[];
}
