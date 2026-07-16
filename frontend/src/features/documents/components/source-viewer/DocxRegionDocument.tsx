import { useEffect, useRef, useState, type ReactNode } from "react";

import { fitContentWidthScale, stepSourceZoom } from "@/features/source-viewer/utils/sourceViewer";
import {
  FallbackNotice,
  ImageAssetStrip,
  SourceViewerError,
  ViewerZoomControls,
  type ContentScaleMode,
} from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import {
  highlightFirstSourceText,
  measureElementContent,
  readableError,
  shouldIgnoreViewerShortcut,
  sourceTextCandidates,
} from "@/features/documents/utils/documentRegionViewerUtils";

export function DocxRegionDocument({
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
