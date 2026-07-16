export function compactDocumentTopics(values: string[], limit = 3): { remaining: number; visible: string[] } {
  const seen = new Set<string>();
  const visible: string[] = [];
  let total = 0;

  values.forEach((value) => {
    const topic = value.trim();
    const key = topic.toLowerCase();
    if (!topic || seen.has(key)) return;
    seen.add(key);
    total += 1;
    if (visible.length < limit) visible.push(topic);
  });

  return { remaining: Math.max(0, total - visible.length), visible };
}

export function hasActiveDocumentFilters(search: string, statusFilter: string, ingestFilter: string, spaceFilter = ""): boolean {
  return Boolean(search.trim()) || statusFilter !== "all" || ingestFilter !== "all" || Boolean(spaceFilter.trim());
}

export function shortDocumentId(id: string, lead = 8, tail = 4): string {
  const compact = id.trim();
  if (compact.length <= lead + tail + 1) return compact;
  return `${compact.slice(0, lead)}...${compact.slice(-tail)}`;
}

export function resultCountLabel(count: number): string {
  return `${count} result${count === 1 ? "" : "s"}`;
}
