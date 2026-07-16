import { Users } from "lucide-react";
import { Skeleton } from "@/components/layout/Common";

export function SpacePathList({ paths }: { paths: string[] }) {
  if (paths.length === 0) return <span className="text-secondary">No spaces</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {paths.map((path) => (
        <span key={path} className="sv-pill">
          {path}
        </span>
      ))}
    </div>
  );
}

export function AccessMetric({ label, loading, value }: { label: string; loading: boolean; value: string }) {
  return (
    <div className="sv-metric" aria-busy={loading} data-cursor-glow>
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Users size={17} />
        </span>
        <span>
          <span className="block text-label-md text-secondary">{label}</span>
          {loading ? (
            <>
              <span className="sr-only">Loading {label.toLowerCase()}</span>
              <Skeleton className="mt-1 h-5 w-12" />
            </>
          ) : <strong className="text-body-lg text-on-surface">{value}</strong>}
        </span>
      </div>
    </div>
  );
}

export function UserTableSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }, (_, index) => (
        <tr key={index}>
          <td colSpan={7}>
            <div className="grid gap-2 py-1">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64 max-w-full" />
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}
