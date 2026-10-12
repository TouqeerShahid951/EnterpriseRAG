export function ChunkPreview({ chunkId, excerpt }: { chunkId: string; excerpt: string }) {
  return (
    <details className="rag-eval-chunk-preview">
      <summary>Chunk {chunkId}</summary>
      <div className="rag-eval-chunk-tooltip" role="tooltip">
        <strong>Retrieved text</strong>
        <p>{excerpt || "No text was available for this candidate."}</p>
        <small>Click the chunk ID to keep this preview open.</small>
      </div>
    </details>
  );
}
