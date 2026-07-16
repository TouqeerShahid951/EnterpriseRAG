

export function setTrimmedParam(params: URLSearchParams, key: string, value: string | undefined) {
  const trimmed = value?.trim();
  if (trimmed) params.set(key, trimmed);
}
