import { useEffect, useMemo, useState, type ReactNode } from "react";
import { FileSearch } from "lucide-react";

import { documentsApi } from "@/lib/api/contracts";
import {
  sourceDocumentKind,
  type SourceDocumentKind,
} from "@/features/source-viewer/utils/sourceViewer";
import {
  FallbackNotice,
  SourceViewerError,
  SourceViewerLoading,
} from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import { DocxRegionDocument } from "@/features/documents/components/source-viewer/DocxRegionDocument";
import { ImageRegionDocument } from "@/features/documents/components/source-viewer/ImageRegionDocument";
import { JsonRegionDocument } from "@/features/documents/components/source-viewer/JsonRegionDocument";
import { PdfRegionDocument } from "@/features/documents/components/source-viewer/PdfRegionDocument";
import { PptxRegionDocument } from "@/features/documents/components/source-viewer/PptxRegionDocument";
import { SpreadsheetRegionDocument } from "@/features/documents/components/source-viewer/SpreadsheetRegionDocument";
import { readableError, type ExactTextTarget } from "@/features/documents/utils/documentRegionViewerUtils";
import { SourceRevisionContext } from "./source-viewer/SourceRevisionContext";
import type { SourceRevision } from "@/types/query";
import type { CitationTarget } from "@/types/query";

const DEFAULT_FALLBACK_MESSAGE = "Exact source highlight is unavailable for this document.";
export { SourceViewerError, SourceViewerLoading };

export interface DocumentRegion {
  bbox: [number, number, number, number] | null;
  confidence?: number | null;
  extractionMethod?: string | null;
  imageAssetId?: string | null;
  imageSourceKind?: string | null;
  page: number | null;
  regionType?: string;
  text: string;
}

const EMPTY_CITATION_TARGETS: CitationTarget[] = [];
const EMPTY_REGIONS: DocumentRegion[] = [];

interface LoadedDocument {
  buffer: ArrayBuffer;
  contentType: string;
  kind: SourceDocumentKind;
}

interface DocumentRegionViewerProps {
  revision?: SourceRevision;
  citationTargets?: CitationTarget[];
  documentId: string;
  documentTitle: string;
  fallbackMessage?: string;
  initialPage: number;
  regions?: DocumentRegion[];
  textTargets?: ExactTextTarget[];
  toolbarEnd?: ReactNode;
}

export function DocumentRegionViewer(props: DocumentRegionViewerProps) {
  return <SourceRevisionContext.Provider value={props.revision}><RegionContent {...props} /></SourceRevisionContext.Provider>;
}

function RegionContent({
  revision,
  citationTargets,
  documentId,
  documentTitle,
  fallbackMessage = DEFAULT_FALLBACK_MESSAGE,
  initialPage,
  regions: explicitRegions,
  textTargets: explicitTextTargets,
  toolbarEnd,
}: DocumentRegionViewerProps) {
  const targets = citationTargets ?? EMPTY_CITATION_TARGETS;
  const regions = useMemo(
    () => [...(explicitRegions ?? EMPTY_REGIONS), ...targets.flatMap(citationTargetRegion)],
    [explicitRegions, targets],
  );
  const textTargets = useMemo(() => [
    ...(explicitTextTargets ?? []),
    ...targets.flatMap((target) => target.kind === "text" && target.exact_text.trim()
      ? [{
        exactText: target.exact_text,
        occurrence: target.occurrence,
        prefix: target.prefix,
        suffix: target.suffix,
      }]
      : []),
  ], [explicitTextTargets, targets]);
  const [loadedDocument, setLoadedDocument] = useState<LoadedDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sourceDocumentKind("", documentTitle) === "pptx") return undefined;
    const controller = new AbortController();

    async function loadDocument() {
      try {
        setError(null);
        setLoadedDocument(null);
        const response = await documentsApi.content(documentId, { signal: controller.signal }, revision);
        if (!response.ok) {
          throw new Error(`The original document could not be opened (${response.status}).`);
        }
        const contentType = response.headers.get("Content-Type") ?? "";
        const buffer = await response.arrayBuffer();
        if (controller.signal.aborted) return;
        setLoadedDocument({
          buffer,
          contentType,
          kind: sourceDocumentKind(contentType, documentTitle),
        });
      } catch (loadError) {
        if (controller.signal.aborted) return;
        setError(readableError(loadError, "The original document could not be opened."));
      }
    }

    void loadDocument();
    return () => controller.abort();
  }, [documentId, documentTitle, revision]);

  if (sourceDocumentKind("", documentTitle) === "pptx" || loadedDocument?.kind === "pptx") {
    return <PptxRegionDocument key={`${documentId}:${initialPage}`} documentId={documentId} fallbackMessage={fallbackMessage} initialPage={initialPage} citedPage={citationTargets !== undefined || explicitRegions?.length ? initialPage : null} regions={regions} toolbarEnd={toolbarEnd} />;
  }

  if (!loadedDocument && !error) return <SourceViewerLoading />;
  if (error) return <SourceViewerError message={error} />;
  if (!loadedDocument) return null;

  if (loadedDocument.kind === "pdf") {
    return (
      <PdfRegionDocument
        buffer={loadedDocument.buffer}
        documentId={documentId}
        fallbackMessage={fallbackMessage}
        initialPage={initialPage}
        regions={regions}
        toolbarEnd={toolbarEnd}
      />
    );
  }

  if (loadedDocument.kind === "docx") {
    return (
      <DocxRegionDocument
        buffer={loadedDocument.buffer}
        documentId={documentId}
        fallbackMessage={fallbackMessage}
        regions={regions}
        textTargets={textTargets}
        toolbarEnd={toolbarEnd}
      />
    );
  }

  if (loadedDocument.kind === "image") {
    return (
      <ImageRegionDocument
        buffer={loadedDocument.buffer}
        contentType={loadedDocument.contentType}
        fallbackMessage={fallbackMessage}
        regions={regions}
        toolbarEnd={toolbarEnd}
      />
    );
  }

  if (loadedDocument.kind === "json") {
    return (
      <JsonRegionDocument
        buffer={loadedDocument.buffer}
        fallbackMessage={fallbackMessage}
        targets={targets.filter((target) => target.kind === "json")}
        toolbarEnd={toolbarEnd}
      />
    );
  }

  if (loadedDocument.kind === "spreadsheet") {
    return (
      <SpreadsheetRegionDocument
        buffer={loadedDocument.buffer}
        documentTitle={documentTitle}
        fallbackMessage={fallbackMessage}
        targets={targets.filter((target) => target.kind === "spreadsheet")}
        toolbarEnd={toolbarEnd}
      />
    );
  }

  return (
    <div className="source-viewer-state">
      <FileSearch aria-hidden="true" size={24} />
      <h2>Preview unavailable</h2>
      <p>This file type cannot be rendered in the internal viewer. Use the original file action.</p>
      <FallbackNotice message={fallbackMessage} />
    </div>
  );
}

function citationTargetRegion(target: CitationTarget): DocumentRegion[] {
  if (target.kind !== "page" && target.kind !== "slide" && target.kind !== "image") return [];
  return [{
    bbox: target.bbox,
    confidence: target.confidence,
    extractionMethod: target.extraction_method,
    imageAssetId: target.image_asset_id,
    imageSourceKind: target.image_source_kind,
    page: target.kind === "image" ? null : target.page,
    regionType: target.kind === "image" ? "image" : target.region_type,
    text: target.exact_text,
  }];
}
