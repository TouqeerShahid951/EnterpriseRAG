import { useEffect, useRef, useState, type ReactNode } from "react";

import { fitContentScale, stepSourceZoom } from "@/features/source-viewer/utils/sourceViewer";
import { FallbackNotice, ViewerZoomControls, type ContentScaleMode } from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import { shouldIgnoreViewerShortcut } from "@/features/documents/utils/documentRegionViewerUtils";

export function ImageRegionDocument({
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
