import { AlertTriangle, Image as ImageIcon, Maximize2, Minimize2, ZoomIn, ZoomOut } from "lucide-react";

import { documentsApi } from "@/lib/api/contracts";
import { sourceZoomLabel } from "@/features/source-viewer/utils/sourceViewer";
import { readableError } from "@/features/documents/utils/documentRegionViewerUtils";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import { useEffect, useState, type ReactNode } from "react";

export type PdfScaleMode = "custom" | "fit-page" | "fit-width";
export type ContentScaleMode = "custom" | "fit";

export function SourceViewerLoading() {
  return (
    <div className="source-viewer-state source-viewer-state-loading" role="status">
      <div className="source-viewer-document-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>
      <h2>Opening original source</h2>
      <p>Loading the document and source location.</p>
    </div>
  );
}

export function SourceViewerError({ action, guidance, message, title = "Source unavailable" }: SourceViewerErrorProps) {
  return (
    <div className="source-viewer-state source-viewer-state-error" role="alert">
      <AlertTriangle aria-hidden="true" size={24} />
      <h2>{title}</h2>
      <p>{message}</p>
      {guidance ? <p>{guidance}</p> : null}
      {action}
    </div>
  );
}

export function FallbackNotice({ message }: { message: string }) {
  return (
    <p className="source-viewer-notice" role="status">
      <AlertTriangle aria-hidden="true" size={16} />
      {message}
    </p>
  );
}

export function ViewerZoomControls({
  activeMode,
  fitLabel,
  fitMode,
  scale,
  widthMode,
  onActualSize,
  onFit,
  onFitWidth,
  onZoomIn,
  onZoomOut,
}: ViewerZoomControlsProps) {
  return (
    <div className="source-viewer-zoom-controls" aria-label="Zoom controls">
      <button type="button" className="source-viewer-icon-button" onClick={onZoomOut} aria-label="Zoom out" title="Zoom out (-)">
        <ZoomOut aria-hidden="true" size={16} />
      </button>
      <span className="source-viewer-zoom-readout" aria-live="polite">{sourceZoomLabel(scale)}</span>
      <button type="button" className="source-viewer-icon-button" onClick={onZoomIn} aria-label="Zoom in" title="Zoom in (+)">
        <ZoomIn aria-hidden="true" size={16} />
      </button>
      <button
        type="button"
        className={activeMode === fitMode ? "source-viewer-mode-button source-viewer-mode-button-active" : "source-viewer-mode-button"}
        onClick={onFit}
        aria-pressed={activeMode === fitMode}
        title={`${fitLabel} (F)`}
      >
        <Minimize2 aria-hidden="true" size={15} />
        {fitLabel}
      </button>
      {widthMode && onFitWidth ? (
        <button
          type="button"
          className={activeMode === widthMode ? "source-viewer-mode-button source-viewer-mode-button-active" : "source-viewer-mode-button"}
          onClick={onFitWidth}
          aria-pressed={activeMode === widthMode}
          title="Fit width (W)"
        >
          <Maximize2 aria-hidden="true" size={15} />
          Fit width
        </button>
      ) : null}
      <button
        type="button"
        className={activeMode === "custom" && Math.abs(scale - 1) < 0.001 ? "source-viewer-mode-button source-viewer-mode-button-active" : "source-viewer-mode-button"}
        onClick={onActualSize}
        aria-pressed={activeMode === "custom" && Math.abs(scale - 1) < 0.001}
        title="Actual size (0)"
      >
        100%
      </button>
    </div>
  );
}

export function ImageAssetStrip({ documentId, regions }: { documentId: string; regions: DocumentRegion[] }) {
  const assetRegions = imageAssetRegions(regions);
  if (assetRegions.length === 0) return null;
  return (
    <div className="source-viewer-asset-strip" aria-label="Image evidence">
      {assetRegions.map((region) => (
        <ImageAssetPreview
          key={region.imageAssetId}
          documentId={documentId}
          region={region}
        />
      ))}
    </div>
  );
}

function ImageAssetPreview({ documentId, region }: { documentId: string; region: DocumentRegion }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const assetId = region.imageAssetId ?? "";

  useEffect(() => {
    if (!assetId) return undefined;
    const controller = new AbortController();
    let nextObjectUrl: string | null = null;

    async function loadAsset() {
      try {
        setError(null);
        setObjectUrl(null);
        const response = await documentsApi.imageAssetContent(documentId, assetId, { signal: controller.signal });
        if (!response.ok) throw new Error(`Image evidence could not be opened (${response.status}).`);
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        nextObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(nextObjectUrl);
      } catch (loadError) {
        if (!controller.signal.aborted) setError(readableError(loadError, "Image evidence could not be opened."));
      }
    }

    void loadAsset();
    return () => {
      controller.abort();
      if (nextObjectUrl) URL.revokeObjectURL(nextObjectUrl);
    };
  }, [assetId, documentId]);

  return (
    <figure className="source-viewer-asset-item">
      <div className="source-viewer-asset-frame">
        {objectUrl ? <img alt="Extracted image evidence" src={objectUrl} /> : null}
        {!objectUrl && !error ? <ImageIcon aria-hidden="true" size={20} /> : null}
        {error ? <span>{error}</span> : null}
      </div>
      <figcaption>
        <strong>{sourceKindLabel(region.imageSourceKind)}</strong>
        {region.text ? <span>{region.text}</span> : null}
      </figcaption>
    </figure>
  );
}

function imageAssetRegions(regions: DocumentRegion[]): DocumentRegion[] {
  const seen = new Set<string>();
  const unique: DocumentRegion[] = [];
  for (const region of regions) {
    const assetId = region.imageAssetId;
    if (!assetId || seen.has(assetId)) continue;
    seen.add(assetId);
    unique.push(region);
  }
  return unique;
}

function sourceKindLabel(value: string | null | undefined): string {
  if (value === "docx_media") return "DOCX image";
  if (value === "pdf_page_image") return "Scanned page";
  if (value === "pdf_image") return "PDF image";
  if (value === "standalone_image") return "Image";
  return "Image evidence";
}

type SourceViewerErrorProps = {
  action?: ReactNode;
  guidance?: string;
  message: string;
  title?: string;
};

type ViewerZoomControlsProps = {
  activeMode: ContentScaleMode | PdfScaleMode;
  fitLabel: string;
  fitMode: ContentScaleMode | PdfScaleMode;
  scale: number;
  widthMode?: PdfScaleMode;
  onActualSize: () => void;
  onFit: () => void;
  onFitWidth?: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
};
