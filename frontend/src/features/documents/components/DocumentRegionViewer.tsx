import { useEffect, useState, type ReactNode } from "react";
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
import { readableError } from "@/features/documents/utils/documentRegionViewerUtils";

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

interface LoadedDocument {
  buffer: ArrayBuffer;
  contentType: string;
  kind: SourceDocumentKind;
}

interface DocumentRegionViewerProps {
  documentId: string;
  documentTitle: string;
  fallbackMessage?: string;
  initialPage: number;
  regions: DocumentRegion[];
  textCandidates?: string[];
  toolbarEnd?: ReactNode;
}

export function DocumentRegionViewer({
  documentId,
  documentTitle,
  fallbackMessage = DEFAULT_FALLBACK_MESSAGE,
  initialPage,
  regions,
  textCandidates,
  toolbarEnd,
}: DocumentRegionViewerProps) {
  const [loadedDocument, setLoadedDocument] = useState<LoadedDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadDocument() {
      try {
        setError(null);
        setLoadedDocument(null);
        const response = await documentsApi.content(documentId, { signal: controller.signal });
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
  }, [documentId, documentTitle]);

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
        textCandidates={textCandidates}
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
        regions={regions}
        textCandidates={textCandidates}
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
