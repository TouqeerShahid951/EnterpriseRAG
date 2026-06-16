import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { documentsApi } from "../api/contracts";
import { DocumentRegionViewer, SourceViewerError, SourceViewerLoading, type DocumentRegion } from "../components/document/DocumentRegionViewer";
import type { SourceAnchor } from "../types/api";
import { citedSourcePage, sourceTextCandidates, sourceViewerParams } from "../utils/sourceViewer";

const FALLBACK_MESSAGE = "Exact source highlight is unavailable for this document.";

interface LoadedSource {
  anchor: SourceAnchor;
  contentUrl: string;
}

export function SourceViewerPage() {
  const params = useMemo(() => sourceViewerParams(location.search), []);
  const [loadedSource, setLoadedSource] = useState<LoadedSource | null>(null);
  const [error, setError] = useState<string | null>(params ? null : "The source viewer link is missing a document or chunk identifier.");

  useEffect(() => {
    if (!params) return;
    const { chunkId, documentId } = params;
    let disposed = false;

    async function loadSource(sourceDocumentId: string, sourceChunkId: string) {
      try {
        setError(null);
        const anchor = await documentsApi.source(sourceDocumentId, sourceChunkId);
        if (disposed) return;
        setLoadedSource({
          anchor,
          contentUrl: documentsApi.contentUrl(sourceDocumentId),
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

  const anchor = loadedSource?.anchor;
  const pageNumber = anchor ? citedSourcePage(anchor) : null;
  const regions = useMemo(() => (anchor ? sourceAnchorRegions(anchor) : []), [anchor]);
  const candidates = useMemo(() => (anchor ? sourceTextCandidates(anchor) : []), [anchor]);

  return (
    <main className="source-viewer-shell">
      <header className="source-viewer-header">
        <div className="source-viewer-heading">
          <a className="source-viewer-back" href="/chat">
            <ArrowLeft aria-hidden="true" size={16} />
            Back to chat
          </a>
          <p className="sv-eyebrow">Original Source</p>
          <h1>{anchor?.doc_title ?? "Source viewer"}</h1>
          {anchor ? (
            <p>
              {pageNumber ? `Cited page ${pageNumber}` : "Cited location"}
              <span aria-hidden="true"> / </span>
              {anchor.group_path}
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

      <section className="source-viewer-stage" aria-live="polite">
        {!loadedSource && !error ? <SourceViewerLoading /> : null}
        {error ? <SourceViewerError message={error} /> : null}
        {loadedSource ? (
          <DocumentRegionViewer
            documentId={loadedSource.anchor.doc_id}
            documentTitle={loadedSource.anchor.doc_title}
            fallbackMessage={FALLBACK_MESSAGE}
            initialPage={citedSourcePage(loadedSource.anchor)}
            regions={regions}
            textCandidates={candidates}
          />
        ) : null}
      </section>
    </main>
  );
}

function sourceAnchorRegions(anchor: SourceAnchor): DocumentRegion[] {
  return (anchor.source_regions ?? []).map((region) => ({
    bbox: region.bbox,
    confidence: region.confidence,
    extractionMethod: region.extraction_method,
    imageAssetId: region.image_asset_id,
    imageSourceKind: region.image_source_kind,
    page: region.page,
    regionType: region.region_type,
    text: region.text,
  }));
}
