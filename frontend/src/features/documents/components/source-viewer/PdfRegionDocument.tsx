import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import {
  clampSourcePage,
  fitPdfPageScale,
  fitPdfWidthScale,
  sourcePageFromInput,
  stepSourceZoom,
} from "@/features/source-viewer/utils/sourceViewer";
import {
  FallbackNotice,
  ImageAssetStrip,
  SourceViewerError,
  ViewerZoomControls,
  type PdfScaleMode,
} from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import {
  isRenderCancellation,
  readableError,
  shouldIgnoreViewerShortcut,
} from "@/features/documents/utils/documentRegionViewerUtils";

export function PdfRegionDocument({
  buffer,
  documentId,
  fallbackMessage,
  initialPage,
  regions,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  documentId: string;
  fallbackMessage: string;
  initialPage: number;
  regions: DocumentRegion[];
  toolbarEnd?: ReactNode;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pdfDocument, setPdfDocument] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(initialPage);
  const [pageCount, setPageCount] = useState(0);
  const [containerSize, setContainerSize] = useState<{ height: number; width: number } | null>(null);
  const [viewport, setViewport] = useState<{ height: number; scale: number; width: number } | null>(null);
  const [scaleMode, setScaleMode] = useState<PdfScaleMode>("fit-page");
  const [customScale, setCustomScale] = useState(1);
  const [pageInput, setPageInput] = useState(`${initialPage}`);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [isRendering, setIsRendering] = useState(true);
  const citedRegions = regions.filter((region) => region.page === initialPage && region.bbox !== null);
  const visibleRegions = regions.filter((region) => region.page === pageNumber && region.bbox !== null);
  const citedPage = clampSourcePage(initialPage, pageCount || initialPage);
  const fitContainerSize = scaleMode === "custom" ? null : containerSize;
  const activeScale = scaleMode === "custom" ? customScale : viewport?.scale ?? customScale;

  const goToPreviousPage = () => {
    if (!pageCount) return;
    setPageNumber((page) => clampSourcePage(page - 1, pageCount));
  };
  const goToNextPage = () => {
    if (!pageCount) return;
    setPageNumber((page) => clampSourcePage(page + 1, pageCount));
  };
  const returnToCitedPage = () => setPageNumber(citedPage);
  const zoomOut = () => {
    setCustomScale(stepSourceZoom(activeScale, "out"));
    setScaleMode("custom");
  };
  const zoomIn = () => {
    setCustomScale(stepSourceZoom(activeScale, "in"));
    setScaleMode("custom");
  };
  const showActualSize = () => {
    setCustomScale(1);
    setScaleMode("custom");
  };

  useEffect(() => {
    let disposed = false;
    let openedDocument: PDFDocumentProxy | null = null;

    async function openPdf() {
      try {
        setRenderError(null);
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        const loadingTask = pdfjs.getDocument({ data: new Uint8Array(buffer.slice(0)) });
        openedDocument = await loadingTask.promise;
        if (disposed) {
          await openedDocument.destroy();
          return;
        }
        setPdfDocument(openedDocument);
        setPageCount(openedDocument.numPages);
        setPageNumber(clampSourcePage(initialPage, openedDocument.numPages));
      } catch (openError) {
        if (!disposed) setRenderError(readableError(openError, "The PDF could not be rendered."));
      }
    }

    void openPdf();
    return () => {
      disposed = true;
      if (openedDocument) void openedDocument.destroy();
    };
  }, [buffer, initialPage]);

  useEffect(() => setPageInput(`${pageNumber}`), [pageNumber]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const updateContainerSize = () => {
      setContainerSize((previousSize) => {
        const nextSize = {
          height: Math.floor(container.clientHeight),
          width: Math.floor(container.clientWidth),
        };
        if (nextSize.height <= 0 || nextSize.width <= 0) return previousSize;
        return !previousSize || nextSize.height !== previousSize.height || nextSize.width !== previousSize.width
          ? nextSize
          : previousSize;
      });
    };

    updateContainerSize();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateContainerSize);
      return () => window.removeEventListener("resize", updateContainerSize);
    }

    const observer = new ResizeObserver(updateContainerSize);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (shouldIgnoreViewerShortcut(event)) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goToPreviousPage();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goToNextPage();
      } else if (event.key === "-") {
        event.preventDefault();
        zoomOut();
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomIn();
      } else if (event.key === "0") {
        event.preventDefault();
        showActualSize();
      } else if (event.key.toLowerCase() === "f") {
        event.preventDefault();
        setScaleMode("fit-page");
      } else if (event.key.toLowerCase() === "w") {
        event.preventDefault();
        setScaleMode("fit-width");
      } else if (event.key.toLowerCase() === "c") {
        event.preventDefault();
        returnToCitedPage();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeScale, citedPage, pageCount]);

  useEffect(() => {
    const activeDocument = pdfDocument;
    const canvas = canvasRef.current;
    if (!activeDocument || !canvas || (scaleMode !== "custom" && !fitContainerSize)) return;
    const activeCanvas = canvas;
    const measuredContainerSize = fitContainerSize;
    let disposed = false;
    let renderTask: RenderTask | null = null;

    async function renderPage(documentToRender: PDFDocumentProxy, targetCanvas: HTMLCanvasElement) {
      try {
        setIsRendering(true);
        setRenderError(null);
        const page = await documentToRender.getPage(pageNumber);
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = scaleMode === "fit-page"
          ? fitPdfPageScale({
            containerHeight: measuredContainerSize?.height ?? 1,
            containerWidth: measuredContainerSize?.width ?? 1,
            pageHeight: baseViewport.height,
            pageWidth: baseViewport.width,
          })
          : scaleMode === "fit-width"
            ? fitPdfWidthScale({
              containerWidth: measuredContainerSize?.width ?? 1,
              pageWidth: baseViewport.width,
            })
            : customScale;
        const nextViewport = page.getViewport({ scale });
        const outputScale = Math.min(window.devicePixelRatio || 1, 2);
        const context = targetCanvas.getContext("2d");
        if (!context) throw new Error("Canvas rendering is unavailable.");

        targetCanvas.width = Math.floor(nextViewport.width * outputScale);
        targetCanvas.height = Math.floor(nextViewport.height * outputScale);
        targetCanvas.style.width = `${nextViewport.width}px`;
        targetCanvas.style.height = `${nextViewport.height}px`;
        renderTask = page.render({
          canvasContext: context,
          viewport: nextViewport,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        });
        await renderTask.promise;
        if (!disposed) {
          setViewport({ height: nextViewport.height, scale, width: nextViewport.width });
          setIsRendering(false);
        }
      } catch (pageError) {
        if (disposed || isRenderCancellation(pageError)) return;
        setRenderError(readableError(pageError, "The cited PDF page could not be rendered."));
        setIsRendering(false);
      }
    }

    void renderPage(activeDocument, activeCanvas);
    return () => {
      disposed = true;
      renderTask?.cancel();
    };
  }, [customScale, fitContainerSize?.height, fitContainerSize?.width, pageNumber, pdfDocument, scaleMode]);

  function commitPageInput() {
    const nextPage = sourcePageFromInput(pageInput, pageNumber, pageCount || pageNumber);
    setPageNumber(nextPage);
    setPageInput(`${nextPage}`);
  }

  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-page-controls" aria-label="PDF page navigation">
            <button type="button" disabled={pageNumber <= 1} onClick={goToPreviousPage} aria-label="Previous page" title="Previous page">
              <ChevronLeft aria-hidden="true" size={16} />
              <span className="source-viewer-control-text">Previous</span>
            </button>
            <label className="source-viewer-page-input-label">
              <span>Page</span>
              <input
                aria-label="Page number"
                disabled={!pageCount}
                inputMode="numeric"
                min={1}
                max={pageCount || undefined}
                type="text"
                value={pageInput}
                onBlur={commitPageInput}
                onChange={(event) => setPageInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.currentTarget.blur();
                  } else if (event.key === "Escape") {
                    setPageInput(`${pageNumber}`);
                    event.currentTarget.blur();
                  }
                }}
              />
              <span>{pageCount ? `/ ${pageCount}` : "/ ..."}</span>
            </label>
            <button type="button" disabled={!pageCount || pageNumber >= pageCount} onClick={goToNextPage} aria-label="Next page" title="Next page">
              <span className="source-viewer-control-text">Next</span>
              <ChevronRight aria-hidden="true" size={16} />
            </button>
          </div>

          <ViewerZoomControls
            activeMode={scaleMode}
            fitLabel="Fit page"
            fitMode="fit-page"
            scale={activeScale}
            widthMode="fit-width"
            onActualSize={showActualSize}
            onFit={() => setScaleMode("fit-page")}
            onFitWidth={() => setScaleMode("fit-width")}
            onZoomIn={zoomIn}
            onZoomOut={zoomOut}
          />
        </div>

        <div className="source-viewer-toolbar-end">
          {pageNumber !== citedPage ? (
            <button className="source-viewer-jump" type="button" onClick={returnToCitedPage}>
              <RotateCcw aria-hidden="true" size={15} />
              Return to cited page
            </button>
          ) : toolbarEnd ? (
            toolbarEnd
          ) : null}
        </div>
      </div>

      {citedRegions.length === 0 ? <FallbackNotice message={fallbackMessage} /> : null}
      <ImageAssetStrip documentId={documentId} regions={regions} />
      {renderError ? <SourceViewerError message={renderError} /> : null}

      <div ref={scrollRef} className="source-viewer-pdf-scroll">
        <div
          className={`source-viewer-pdf-page ${isRendering ? "is-rendering" : ""} ${viewport ? "" : "source-viewer-pdf-page-unmeasured"}`}
          style={viewport ? { height: viewport.height, width: viewport.width } : undefined}
        >
          <canvas ref={canvasRef} aria-label={`PDF page ${pageNumber}`} />
          {viewport ? (
            <div className="source-viewer-pdf-overlay" aria-label="Source region highlights">
              {visibleRegions.map((region, index) => (
                <PdfRegionHighlight key={`${region.page}-${index}`} region={region} scale={viewport.scale} />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function PdfRegionHighlight({ region, scale }: { region: DocumentRegion; scale: number }) {
  if (!region.bbox) return null;
  const [x0, y0, x1, y1] = region.bbox;
  return (
    <span
      className="source-viewer-pdf-highlight"
      title={region.text}
      style={{
        height: Math.max(2, y1 - y0) * scale,
        left: Math.max(0, x0) * scale,
        top: Math.max(0, y0) * scale,
        width: Math.max(2, x1 - x0) * scale,
      }}
    />
  );
}
