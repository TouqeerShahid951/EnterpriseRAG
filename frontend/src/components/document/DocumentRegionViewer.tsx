import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  Image as ImageIcon,
  Maximize2,
  Minimize2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { documentsApi } from "../../api/contracts";
import {
  clampSourcePage,
  fitContentScale,
  fitContentWidthScale,
  fitPdfPageScale,
  fitPdfWidthScale,
  jsonDocumentText,
  jsonHighlightRange,
  normalizeSourceText,
  sourceDocumentKind,
  sourcePageFromInput,
  sourceZoomLabel,
  stepSourceZoom,
  type SourceDocumentKind,
} from "../../utils/sourceViewer";

const DEFAULT_FALLBACK_MESSAGE = "Exact source highlight is unavailable for this document.";
type PdfScaleMode = "custom" | "fit-page" | "fit-width";
type ContentScaleMode = "custom" | "fit";

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

function JsonRegionDocument({
  buffer,
  fallbackMessage,
  regions,
  textCandidates,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  fallbackMessage: string;
  regions: DocumentRegion[];
  textCandidates?: string[];
  toolbarEnd?: ReactNode;
}) {
  const { prettyText, rawText } = jsonDocumentText(buffer);
  const candidates = sourceTextCandidates(regions, textCandidates);
  const prettyHighlight = jsonHighlightRange(prettyText, candidates);
  const rawHighlight = prettyHighlight ? null : jsonHighlightRange(rawText, candidates);
  const highlight = prettyHighlight ?? rawHighlight;
  const displayText = rawHighlight ? rawText : prettyText || rawText;
  const lines = jsonLines(displayText);
  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">JSON source</div>
        </div>
        <div className="source-viewer-toolbar-end">{toolbarEnd}</div>
      </div>
      {highlight ? null : <FallbackNotice message={fallbackMessage} />}
      <div className="source-viewer-json-scroll">
        <div className="source-viewer-json-document" role="region" aria-label="JSON source preview">
          <div className="source-viewer-json-ruler" aria-hidden="true" />
          <pre className="source-viewer-json-code">
            {lines.map((line) => (
              <span className="source-viewer-json-line" key={line.number}>
                <span className="source-viewer-json-line-number" aria-hidden="true">{line.number}</span>
                <span className="source-viewer-json-line-content">
                  {renderJsonLine(line, highlight)}
                </span>
              </span>
            ))}
          </pre>
        </div>
      </div>
    </div>
  );
}

function jsonLines(text: string): Array<{ end: number; number: number; start: number; text: string }> {
  const sourceLines = text.split("\n");
  let offset = 0;
  return sourceLines.map((line, index) => {
    const start = offset;
    const end = start + line.length;
    offset = end + 1;
    return { end, number: index + 1, start, text: line };
  });
}

function renderJsonLine(
  line: { end: number; start: number; text: string },
  highlight: { start: number; end: number } | null,
) {
  if (!highlight || highlight.end <= line.start || highlight.start >= line.end) {
    return <>{renderJsonSyntax(line.text || " ", "plain")}</>;
  }
  const highlightStart = Math.max(0, highlight.start - line.start);
  const highlightEnd = Math.min(line.text.length, highlight.end - line.start);
  return (
    <>
      {renderJsonSyntax(line.text.slice(0, highlightStart), "before")}
      <mark className="source-viewer-json-highlight">{renderJsonSyntax(line.text.slice(highlightStart, highlightEnd), "highlight")}</mark>
      {renderJsonSyntax(line.text.slice(highlightEnd) || " ", "after")}
    </>
  );
}

function renderJsonSyntax(text: string, keyPrefix: string) {
  const nodes: ReactNode[] = [];
  const tokenPattern = /("(?:\\.|[^"\\])*")(\s*:)?|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}\[\],:]/g;
  let cursor = 0;
  let tokenIndex = 0;
  for (const match of text.matchAll(tokenPattern)) {
    const index = match.index ?? 0;
    if (index > cursor) nodes.push(text.slice(cursor, index));
    if (match[1]) {
      const isKey = Boolean(match[2]);
      nodes.push(
        <span className={isKey ? "source-viewer-json-token-key" : "source-viewer-json-token-string"} key={`${keyPrefix}-${tokenIndex}-string`}>
          {match[1]}
        </span>
      );
      if (match[2]) {
        nodes.push(<span className="source-viewer-json-token-punctuation" key={`${keyPrefix}-${tokenIndex}-colon`}>{match[2]}</span>);
      }
    } else {
      const token = match[0];
      const className = jsonTokenClass(token);
      nodes.push(<span className={className} key={`${keyPrefix}-${tokenIndex}`}>{token}</span>);
    }
    cursor = index + match[0].length;
    tokenIndex += 1;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function jsonTokenClass(token: string): string {
  if (/^-?\d/.test(token)) return "source-viewer-json-token-number";
  if (token === "true" || token === "false") return "source-viewer-json-token-boolean";
  if (token === "null") return "source-viewer-json-token-null";
  return "source-viewer-json-token-punctuation";
}

export function SourceViewerLoading() {
  return (
    <div className="source-viewer-state">
      <span className="source-viewer-spinner" aria-hidden="true" />
      <h2>Opening original source</h2>
      <p>Loading the document and source location.</p>
    </div>
  );
}

export function SourceViewerError({ message }: { message: string }) {
  return (
    <div className="source-viewer-state source-viewer-state-error" role="alert">
      <AlertTriangle aria-hidden="true" size={24} />
      <h2>Source unavailable</h2>
      <p>{message}</p>
    </div>
  );
}

function PdfRegionDocument({
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

function DocxRegionDocument({
  buffer,
  documentId,
  fallbackMessage,
  regions,
  textCandidates,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  documentId: string;
  fallbackMessage: string;
  regions: DocumentRegion[];
  textCandidates?: string[];
  toolbarEnd?: ReactNode;
}) {
  const documentRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const styleRef = useRef<HTMLDivElement>(null);
  const [matched, setMatched] = useState<boolean | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [containerSize, setContainerSize] = useState<{ height: number; width: number } | null>(null);
  const [contentSize, setContentSize] = useState<{ height: number; width: number } | null>(null);
  const [scaleMode, setScaleMode] = useState<ContentScaleMode>("fit");
  const [customScale, setCustomScale] = useState(1);
  const activeScale = contentSize && containerSize
    ? scaleMode === "fit"
      ? fitContentWidthScale({
        containerWidth: containerSize.width,
        contentWidth: contentSize.width,
      })
      : customScale
    : customScale;
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
      if (event.key === "-") {
        event.preventDefault();
        zoomOut();
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomIn();
      } else if (event.key === "0") {
        event.preventDefault();
        showActualSize();
      } else if (event.key.toLowerCase() === "f" || event.key.toLowerCase() === "w") {
        event.preventDefault();
        setScaleMode("fit");
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeScale]);

  useEffect(() => {
    const container = documentRef.current;
    const styleContainer = styleRef.current;
    if (!container || !styleContainer) return;
    const docxContainer = container;
    const docxStyleContainer = styleContainer;
    let disposed = false;

    async function renderDocx() {
      try {
        setMatched(null);
        setRenderError(null);
        docxContainer.replaceChildren();
        docxStyleContainer.replaceChildren();
        const { renderAsync } = await import("docx-preview");
        await renderAsync(buffer.slice(0), docxContainer, docxStyleContainer, {
          breakPages: true,
          ignoreFonts: false,
          inWrapper: true,
          useBase64URL: true,
        });
        if (disposed) return;
        setContentSize(measureElementContent(docxContainer));
        const didMatch = highlightFirstSourceText(docxContainer, sourceTextCandidates(regions, textCandidates));
        setMatched(didMatch);
        requestAnimationFrame(() => docxContainer.querySelector<HTMLElement>(".source-viewer-docx-highlight")?.scrollIntoView({ block: "center" }));
      } catch (docxError) {
        if (!disposed) setRenderError(readableError(docxError, "The DOCX file could not be rendered."));
      }
    }

    void renderDocx();
    return () => {
      disposed = true;
    };
  }, [buffer, regions, textCandidates]);

  useEffect(() => {
    if (!matched) return;
    const highlight = documentRef.current?.querySelector<HTMLElement>(".source-viewer-docx-highlight");
    requestAnimationFrame(() => highlight?.scrollIntoView({ block: "center" }));
  }, [activeScale, matched]);

  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">DOCX source</div>
          <ViewerZoomControls
            activeMode={scaleMode}
            fitLabel="Fit width"
            fitMode="fit"
            scale={activeScale}
            onActualSize={showActualSize}
            onFit={() => setScaleMode("fit")}
            onZoomIn={zoomIn}
            onZoomOut={zoomOut}
          />
        </div>
        <div className="source-viewer-toolbar-end">{toolbarEnd}</div>
      </div>
      {matched === false ? <FallbackNotice message={fallbackMessage} /> : null}
      <ImageAssetStrip documentId={documentId} regions={regions} />
      {renderError ? <SourceViewerError message={renderError} /> : null}
      <div ref={styleRef} />
      <div ref={scrollRef} className="source-viewer-docx-scroll">
        <div
          className="source-viewer-docx-scale-frame"
          style={contentSize ? { height: contentSize.height * activeScale, width: contentSize.width * activeScale } : undefined}
        >
          <div
            ref={documentRef}
            className="source-viewer-docx-document"
            style={{ transform: `scale(${activeScale})` }}
          />
        </div>
      </div>
    </div>
  );
}

function ImageRegionDocument({
  buffer,
  contentType,
  fallbackMessage,
  regions,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  contentType: string;
  fallbackMessage: string;
  regions: DocumentRegion[];
  toolbarEnd?: ReactNode;
}) {
  const imageRef = useRef<HTMLImageElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [contentObjectUrl, setContentObjectUrl] = useState<string | null>(null);
  const [naturalSize, setNaturalSize] = useState<{ height: number; width: number } | null>(null);
  const [containerSize, setContainerSize] = useState<{ height: number; width: number } | null>(null);
  const [scaleMode, setScaleMode] = useState<ContentScaleMode>("fit");
  const [customScale, setCustomScale] = useState(1);
  const visibleRegions = regions.filter((region) => region.bbox !== null);
  const activeScale = naturalSize && containerSize
    ? scaleMode === "fit"
      ? fitContentScale({
        containerHeight: containerSize.height,
        containerWidth: containerSize.width,
        contentHeight: naturalSize.height,
        contentWidth: naturalSize.width,
      })
      : customScale
    : customScale;
  const renderedSize = naturalSize
    ? { height: naturalSize.height * activeScale, width: naturalSize.width * activeScale }
    : null;
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
    const objectUrl = URL.createObjectURL(new Blob([buffer.slice(0)], { type: contentType || "image/jpeg" }));
    setContentObjectUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [buffer, contentType]);

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
      if (event.key === "-") {
        event.preventDefault();
        zoomOut();
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomIn();
      } else if (event.key === "0") {
        event.preventDefault();
        showActualSize();
      } else if (event.key.toLowerCase() === "f" || event.key.toLowerCase() === "w") {
        event.preventDefault();
        setScaleMode("fit");
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeScale]);

  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">Image source</div>
          <ViewerZoomControls
            activeMode={scaleMode}
            fitLabel="Fit image"
            fitMode="fit"
            scale={activeScale}
            onActualSize={showActualSize}
            onFit={() => setScaleMode("fit")}
            onZoomIn={zoomIn}
            onZoomOut={zoomOut}
          />
        </div>
        <div className="source-viewer-toolbar-end">{toolbarEnd}</div>
      </div>

      {visibleRegions.length === 0 ? <FallbackNotice message={fallbackMessage} /> : null}

      <div ref={scrollRef} className="source-viewer-image-scroll">
        <div
          className="source-viewer-image-stage"
          style={renderedSize ? { height: renderedSize.height, width: renderedSize.width } : undefined}
        >
          {contentObjectUrl ? (
            <img
              ref={imageRef}
              alt="Original source image"
              className="source-viewer-image"
              src={contentObjectUrl}
              style={renderedSize ? { height: renderedSize.height, width: renderedSize.width } : undefined}
              onLoad={(event) => {
                const image = event.currentTarget;
                setNaturalSize({ height: image.naturalHeight, width: image.naturalWidth });
              }}
            />
          ) : null}
          {naturalSize && renderedSize ? (
            <div className="source-viewer-image-overlay" aria-label="Source region highlights">
              {visibleRegions.map((region, index) => (
                <ImageRegionHighlight
                  key={`${region.page ?? "image"}-${index}`}
                  naturalSize={naturalSize}
                  region={region}
                  renderedSize={renderedSize}
                />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ImageRegionHighlight({
  naturalSize,
  region,
  renderedSize,
}: {
  naturalSize: { height: number; width: number };
  region: DocumentRegion;
  renderedSize: { height: number; width: number };
}) {
  if (!region.bbox) return null;
  const [x0, y0, x1, y1] = region.bbox;
  const scaleX = renderedSize.width / Math.max(1, naturalSize.width);
  const scaleY = renderedSize.height / Math.max(1, naturalSize.height);
  return (
    <span
      className="source-viewer-image-highlight"
      title={region.text}
      style={{
        height: Math.max(2, y1 - y0) * scaleY,
        left: Math.max(0, x0) * scaleX,
        top: Math.max(0, y0) * scaleY,
        width: Math.max(2, x1 - x0) * scaleX,
      }}
    />
  );
}

function ViewerZoomControls({
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
}: {
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
}) {
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

function ImageAssetStrip({ documentId, regions }: { documentId: string; regions: DocumentRegion[] }) {
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

function FallbackNotice({ message }: { message: string }) {
  return (
    <p className="source-viewer-notice" role="status">
      <AlertTriangle aria-hidden="true" size={16} />
      {message}
    </p>
  );
}

function sourceTextCandidates(regions: DocumentRegion[], explicitCandidates: string[] | undefined): string[] {
  const candidates = [...(explicitCandidates ?? []), ...regions.map((region) => region.text)];
  const seen = new Set<string>();
  return candidates.filter((candidate) => {
    const normalized = normalizeSourceText(candidate);
    if (!normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function highlightFirstSourceText(root: HTMLElement, candidates: string[]): boolean {
  const indexedText = indexRenderedText(root);
  if (!indexedText.normalized) return false;

  for (const candidate of candidates) {
    for (const query of matchingVariants(candidate)) {
      const matchStart = indexedText.normalized.indexOf(query);
      if (matchStart < 0) continue;
      wrapMatchedText(indexedText.positions.slice(matchStart, matchStart + query.length));
      return true;
    }
  }
  return false;
}

function indexRenderedText(root: HTMLElement): { normalized: string; positions: TextPosition[] } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || parent.closest("script, style")) return NodeFilter.FILTER_REJECT;
      return node.nodeValue?.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  const positions: TextPosition[] = [];
  let normalized = "";
  let pendingSpace: TextPosition | null = null;
  let node = walker.nextNode() as Text | null;

  while (node) {
    const value = node.nodeValue ?? "";
    for (let offset = 0; offset < value.length; offset += 1) {
      const character = value[offset];
      if (/\s/.test(character)) {
        if (normalized && !normalized.endsWith(" ")) pendingSpace = { node, offset };
        continue;
      }
      if (pendingSpace) {
        normalized += " ";
        positions.push(pendingSpace);
        pendingSpace = null;
      }
      normalized += character.toLocaleLowerCase();
      positions.push({ node, offset });
    }
    node = walker.nextNode() as Text | null;
  }

  return { normalized, positions };
}

function matchingVariants(candidate: string): string[] {
  const normalized = normalizeSourceText(candidate);
  if (!normalized) return [];
  const variants = [normalized];
  if (normalized.length > 320) variants.push(normalized.slice(0, 320).trim());
  if (normalized.length > 160) variants.push(normalized.slice(0, 160).trim());
  return variants.filter((variant, index) => variant.length >= 16 && variants.indexOf(variant) === index);
}

function wrapMatchedText(positions: TextPosition[]) {
  const groups: TextPosition[][] = [];
  for (const position of positions) {
    const current = groups[groups.length - 1];
    const previous = current?.[current.length - 1];
    if (current && previous?.node === position.node && position.offset <= previous.offset + 1) current.push(position);
    else groups.push([position]);
  }

  for (const group of groups.reverse()) {
    const first = group[0];
    const last = group[group.length - 1];
    const range = document.createRange();
    range.setStart(first.node, first.offset);
    range.setEnd(last.node, last.offset + 1);
    const mark = document.createElement("mark");
    mark.className = "source-viewer-docx-highlight";
    range.surroundContents(mark);
  }
}

function readableError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function isRenderCancellation(error: unknown): boolean {
  return error instanceof Error && error.name === "RenderingCancelledException";
}

function shouldIgnoreViewerShortcut(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return true;
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return target.isContentEditable || tagName === "input" || tagName === "select" || tagName === "textarea";
}

function measureElementContent(element: HTMLElement): { height: number; width: number } {
  const rect = element.getBoundingClientRect();
  return {
    height: Math.max(1, element.scrollHeight, element.offsetHeight, Math.ceil(rect.height)),
    width: Math.max(1, element.scrollWidth, element.offsetWidth, Math.ceil(rect.width)),
  };
}

interface TextPosition {
  node: Text;
  offset: number;
}
