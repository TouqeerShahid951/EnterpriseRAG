import { useEffect, useState } from "react";

export function useElapsedSeconds(createdAt: string): number {
  const [elapsedSeconds, setElapsedSeconds] = useState(() => secondsSince(createdAt));

  useEffect(() => {
    setElapsedSeconds(secondsSince(createdAt));
    const timer = window.setInterval(() => {
      setElapsedSeconds(secondsSince(createdAt));
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [createdAt]);

  return elapsedSeconds;
}

function secondsSince(createdAt: string): number {
  const createdTime = new Date(createdAt).getTime();
  if (Number.isNaN(createdTime)) return 0;
  return Math.max(0, Math.floor((Date.now() - createdTime) / 1000));
}

export function secondsBetween(startedAt: string, endedAt: string): number {
  const startedTime = new Date(startedAt).getTime();
  const endedTime = new Date(endedAt).getTime();
  if (Number.isNaN(startedTime) || Number.isNaN(endedTime)) return 0;
  return Math.max(0, Math.floor((endedTime - startedTime) / 1000));
}

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

export function formatLatencyMs(latencyMs: number): string {
  if (!Number.isFinite(latencyMs) || latencyMs <= 0) return "0s";
  return formatElapsed(Math.max(1, Math.round(latencyMs / 1000)));
}
