export async function* parseSseStream<TEvent>(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<TEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        const event = parseSsePart(part);
        if (event) yield event as TEvent;
      }
    }

    buffer += decoder.decode();
    const event = parseSsePart(buffer);
    if (event) yield event as TEvent;
  } finally {
    reader.releaseLock();
  }
}

function parseSsePart(part: string): unknown {
  const lines = part.split(/\r?\n/);
  const event = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const dataLines = lines
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6));

  if (!event || dataLines.length === 0) return null;

  return { event, data: JSON.parse(dataLines.join("\n")) };
}
