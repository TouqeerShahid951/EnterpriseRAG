import { useEffect, useRef, useState, type ReactNode } from "react";
import { FileSearch, ImageIcon } from "lucide-react";

import { fitContentWidthScale, stepSourceZoom } from "@/features/source-viewer/utils/sourceViewer";
import {
  FallbackNotice,
  ImageAssetStrip,
  SourceViewerError,
  ViewerZoomControls,
  type ContentScaleMode,
} from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import { SourceViewerSearch } from "@/features/documents/components/source-viewer/SourceViewerSearch";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import {
  highlightExactSourceText,
  countRenderedTextMatches,
  highlightRenderedTextMatch,
  measureElementContent,
  readableError,
  shouldIgnoreViewerShortcut,
  type ExactTextTarget,
} from "@/features/documents/utils/documentRegionViewerUtils";

export function DocxRegionDocument({
  buffer,
  documentId,
  fallbackMessage,
  regions,
  textTargets,
  toolbarEnd,
}: {
  buffer: ArrayBuffer;
  documentId: string;
  fallbackMessage: string;
  regions: DocumentRegion[];
  textTargets: ExactTextTarget[];
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
  const [showOriginalDocument, setShowOriginalDocument] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearchQuery, setActiveSearchQuery] = useState("");
  const [searchIndex, setSearchIndex] = useState(0);
  const [searchMatchCount, setSearchMatchCount] = useState(0);
  const [searchStatus, setSearchStatus] = useState<string | undefined>();
  const [isSearching, setIsSearching] = useState(false);
  const hasOnlyImageEvidence = textTargets.length === 0 && regions.some((region) => region.imageAssetId);
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

  function resetSearchResults() {
    setActiveSearchQuery("");
    setSearchIndex(0);
    setSearchMatchCount(0);
    setSearchStatus(undefined);
    setIsSearching(false);
  }

  function runSearch() {
    const query = searchQuery.trim();
    if (!query) {
      resetSearchResults();
      return;
    }
    setActiveSearchQuery(query);
    setSearchIndex(0);
    setSearchMatchCount(0);
    setSearchStatus("Searching…");
    setIsSearching(true);
  }

  function goToSearchResult(direction: -1 | 1) {
    if (!searchMatchCount) return;
    setSearchIndex((currentIndex) => (currentIndex + direction + searchMatchCount) % searchMatchCount);
  }

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
  }, [showOriginalDocument]);

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
        setSearchMatchCount(0);
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
        const didMatch = highlightExactSourceText(docxContainer, textTargets);
        setMatched(didMatch);
        const matchCount = activeSearchQuery ? countRenderedTextMatches(docxContainer, activeSearchQuery) : 0;
        setSearchMatchCount(matchCount);
        if (activeSearchQuery) {
          setSearchStatus(matchCount ? undefined : "No matches");
          if (matchCount) highlightRenderedTextMatch(docxContainer, activeSearchQuery, searchIndex);
        } else {
          setSearchStatus(undefined);
        }
        setIsSearching(false);
        requestAnimationFrame(() => docxContainer.querySelector<HTMLElement>(".source-viewer-docx-highlight")?.scrollIntoView({ block: "center" }));
      } catch (docxError) {
        if (!disposed) {
          setRenderError(readableError(docxError, "The DOCX file could not be rendered."));
          setIsSearching(false);
        }
      }
    }

    void renderDocx();
    return () => {
      disposed = true;
    };
  }, [activeSearchQuery, buffer, searchIndex, showOriginalDocument, textTargets]);

  useEffect(() => {
    const highlight = documentRef.current?.querySelector<HTMLElement>(".source-viewer-search-highlight, .source-viewer-docx-highlight");
    requestAnimationFrame(() => highlight?.scrollIntoView({ block: "center" }));
  }, [activeScale, activeSearchQuery, matched, searchIndex]);

  if (hasOnlyImageEvidence && !showOriginalDocument) {
    return (
      <div className="source-viewer-document source-viewer-image-evidence">
        <div className="source-viewer-toolbar">
          <div className="source-viewer-toolbar-main">
            <div className="source-viewer-file-label">Extracted DOCX image</div>
            <span className="source-viewer-search-unavailable" role="status">Text search is unavailable for image-only previews.</span>
            <SourceViewerSearch disabled onQueryChange={setSearchQuery} onSearch={runSearch} query={searchQuery} />
            <button type="button" className="sv-action-secondary source-viewer-context-toggle" onClick={() => setShowOriginalDocument(true)}>
              <FileSearch aria-hidden="true" size={15} />
              Show in document
            </button>
          </div>
          <div className="source-viewer-toolbar-end">{toolbarEnd}</div>
        </div>
        <ImageAssetStrip documentId={documentId} regions={regions} />
      </div>
    );
  }

  return (
    <div className="source-viewer-document">
      <div className="source-viewer-toolbar">
        <div className="source-viewer-toolbar-main">
          <div className="source-viewer-file-label">DOCX source</div>
          {hasOnlyImageEvidence ? (
            <button type="button" className="sv-action-secondary source-viewer-context-toggle" onClick={() => setShowOriginalDocument(false)}>
              <ImageIcon aria-hidden="true" size={15} />
              Show extracted image
            </button>
          ) : null}
          <SourceViewerSearch
            isSearching={isSearching}
            onNext={() => goToSearchResult(1)}
            onPrevious={() => goToSearchResult(-1)}
            onQueryChange={(query) => { setSearchQuery(query); resetSearchResults(); }}
            onSearch={runSearch}
            query={searchQuery}
            resultLabel={searchMatchCount ? `${searchIndex + 1} of ${searchMatchCount}` : undefined}
            status={isSearching ? "Searching…" : searchStatus}
          />
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
      {matched === false && !hasOnlyImageEvidence ? <FallbackNotice message={fallbackMessage} /> : null}
      {!hasOnlyImageEvidence ? <ImageAssetStrip documentId={documentId} regions={regions} /> : null}
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
