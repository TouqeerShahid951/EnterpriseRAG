import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { documentsApi } from "@/lib/api/contracts";
import { DocumentRegionViewer, SourceViewerError, SourceViewerLoading } from "@/features/documents/components/DocumentRegionViewer";
import type { SourceAnchor } from "@/types/api";
import { citedSourcePage, sourceViewerParams, sourceViewerReturnHref } from "@/features/source-viewer/utils/sourceViewer";
import { SourceCitationNavigator } from "@/features/source-viewer/components/SourceCitationNavigator";

const FALLBACK_MESSAGE = "Exact source highlight is unavailable for this document.";

interface LoadedSource {
  anchor: SourceAnchor | null;
  citations: SourceAnchor[];
  contentUrl: string;
  documentId: string;
  documentTitle: string;
  groupPath: string;
}

export function SourceViewerPage() {
  const params = useMemo(() => sourceViewerParams(location.search), []);
  const isIncompleteLink = !params;
  const [loadedSource, setLoadedSource] = useState<LoadedSource | null>(null);
  const [activeCitationIndex, setActiveCitationIndex] = useState(0);
  const [error, setError] = useState<string | null>(params ? null : "The source viewer link is missing a document identifier.");

  useEffect(() => {
    if (!params) return;
    const { chunkId, citationChunkIds, documentId } = params;
    let disposed = false;

    async function loadSource(sourceDocumentId: string, sourceChunkId: string | null) {
      try {
        setError(null);
        const orderedChunkIds = [...new Set([...citationChunkIds, ...(sourceChunkId ? [sourceChunkId] : [])])];
        const anchor = sourceChunkId ? await documentsApi.source(sourceDocumentId, sourceChunkId, params?.revision) : null;
        const relatedSources = await Promise.allSettled(
          orderedChunkIds.filter((chunk) => chunk !== sourceChunkId).map((chunk) => documentsApi.source(sourceDocumentId, chunk)),
        );
        const anchorsByChunk = new Map<string, SourceAnchor>(anchor ? [[anchor.chunk_id, anchor]] : []);
        relatedSources.forEach((result) => {
          if (result.status === "fulfilled" && result.value.doc_id === sourceDocumentId) anchorsByChunk.set(result.value.chunk_id, result.value);
        });
        const citations = orderedChunkIds.flatMap((chunk) => {
          const citation = anchorsByChunk.get(chunk);
          return citation ? [citation] : [];
        });
        const document = anchor ? null : await documentsApi.get(sourceDocumentId);
        if (disposed) return;
        const activeIndex = sourceChunkId ? citations.findIndex((citation) => citation.chunk_id === sourceChunkId) : -1;
        setActiveCitationIndex(activeIndex >= 0 ? activeIndex : 0);
        setLoadedSource({
          anchor,
          citations,
          contentUrl: documentsApi.contentUrl(sourceDocumentId, params?.revision),
          documentId: sourceDocumentId,
          documentTitle: anchor?.doc_title ?? document?.title ?? "Document preview",
          groupPath: anchor?.group_path ?? document?.group_path ?? "",
        });
      } catch (loadError) {
        if (disposed) return;
        setError(loadError instanceof Error ? loadError.message : "The source location could not be opened.");
      }
    }

    void loadSource(documentId, chunkId);
    return () => {
      disposed = true;
    };
  }, [params]);

  const activeCitation = loadedSource?.citations[activeCitationIndex] ?? loadedSource?.anchor ?? null;
  const anchor = activeCitation;
  const pageNumber = anchor ? citedSourcePage(anchor) : null;
  const returnHref = sourceViewerReturnHref(params);
  const returnLabel = params?.chunkId ? "Back to chat" : "Back to documents";
  return (
    <main className="source-viewer-shell">
      <header className="source-viewer-header">
        <div className="source-viewer-heading">
          <a className="source-viewer-back" href={returnHref}>
            <ArrowLeft aria-hidden="true" size={16} />
            {returnLabel}
          </a>
          <p className="sv-eyebrow">{anchor ? "Original Source" : "Document Preview"}</p>
          <h1>{loadedSource?.documentTitle ?? "Source viewer"}</h1>
          {loadedSource ? (
            <p>
              {anchor ? (pageNumber ? `Cited page ${pageNumber}` : "Cited location") : "Original document"}
              {loadedSource.groupPath ? <><span aria-hidden="true"> / </span>{loadedSource.groupPath}</> : null}
            </p>
          ) : null}
        </div>
        {loadedSource ? (
          <a className="source-viewer-original-link" href={loadedSource.contentUrl} target="_blank" rel="noreferrer">
            <ExternalLink aria-hidden="true" size={16} />
            Open original file
          </a>
        ) : null}
      </header>

      {anchor && !anchor.index_generation_id ? <p role="status">Legacy citation: source revision is unknown.</p> : null}
      <section className="source-viewer-stage" aria-live="polite">
        {!loadedSource && !error ? <SourceViewerLoading /> : null}
        {error ? (
          <SourceViewerError
            title={isIncompleteLink ? "Citation link is incomplete" : "Source could not be opened"}
            message={error}
            guidance={
              isIncompleteLink
                ? "Return to the document library or chat and open the source again."
                : "The document may have moved, been removed, or no longer be available to this account."
            }
            action={<a className="sv-action-primary" href={returnHref}>{returnLabel}</a>}
          />
        ) : null}
        {loadedSource ? (
          <DocumentRegionViewer
            revision={params?.revision}
            documentId={loadedSource.documentId}
            documentTitle={loadedSource.documentTitle}
            fallbackMessage={FALLBACK_MESSAGE}
            initialPage={anchor ? citedSourcePage(anchor) : 1}
            citationTargets={anchor ? anchor.citation_targets ?? [] : undefined}
            toolbarEnd={loadedSource.citations.length > 1 ? (
              <SourceCitationNavigator
                activeIndex={activeCitationIndex}
                citations={loadedSource.citations}
                onNext={() => setActiveCitationIndex((index) => Math.min(index + 1, loadedSource.citations.length - 1))}
                onPrevious={() => setActiveCitationIndex((index) => Math.max(index - 1, 0))}
                onSelect={(index) => setActiveCitationIndex(Math.min(Math.max(index, 0), loadedSource.citations.length - 1))}
              />
            ) : null}
          />
        ) : null}
      </section>
    </main>
  );
}
