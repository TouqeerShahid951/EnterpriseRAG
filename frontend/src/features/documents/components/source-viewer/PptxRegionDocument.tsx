import { useSourceRevision } from "./SourceRevisionContext";
import { useEffect, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";

import { documentsApi } from "@/lib/api/contracts";
import type { DocumentRegion } from "@/features/documents/components/DocumentRegionViewer";
import { ImageRegionDocument } from "@/features/documents/components/source-viewer/ImageRegionDocument";
import { SourceViewerError, SourceViewerLoading } from "@/features/documents/components/source-viewer/DocumentRegionViewerPrimitives";
import { readableError, shouldIgnoreViewerShortcut } from "@/features/documents/utils/documentRegionViewerUtils";

export function PptxRegionDocument({ documentId, fallbackMessage, initialPage, citedPage = null, regions, toolbarEnd }: {
  documentId: string;
  fallbackMessage: string;
  initialPage: number;
  citedPage?: number | null;
  regions: DocumentRegion[];
  toolbarEnd?: ReactNode;
}) {
  const revision = useSourceRevision();
  const [page, setPage] = useState(initialPage);
  const [slides, setSlides] = useState<number[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [catalogAttempt, setCatalogAttempt] = useState(-1);
  const [slide, setSlide] = useState<{ key: string; buffer: ArrayBuffer; contentType: string } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const slideRegions = regions.filter((region) => region.page === page);
  const assetId = slideRegions.find((region) => region.imageSourceKind === "pptx_slide" && region.imageAssetId)?.imageAssetId;
  const requestKey = JSON.stringify([documentId, page, assetId, attempt]);
  const index = slides?.indexOf(page) ?? -1;
  const missingSlide = slides !== null && index < 0;
  const error = catalogAttempt !== attempt ? null : catalogError ?? (missingSlide
    ? slides.length ? "This slide preview is unavailable." : "No slide previews are available yet."
    : failure?.key === requestKey ? failure.message : null);
  const loading = !error && (catalogAttempt !== attempt || slides === null || slide?.key !== requestKey);

  useEffect(() => {
    let disposed = false;
    setCatalogError(null);
    void documentsApi.presentationSlides(documentId, revision).then((result) => {
      if (disposed) return;
      setSlides(result.slides);
      setCatalogAttempt(attempt);
      if (citedPage === null && result.slides.length) setPage((current) => result.slides.includes(current) ? current : result.slides[0]);
    }).catch((loadError) => {
      if (!disposed) {
        setCatalogAttempt(attempt);
        setCatalogError(readableError(loadError, "The slide list could not be opened."));
      }
    });
    return () => { disposed = true; };
  }, [documentId, citedPage, attempt, revision]);

  useEffect(() => {
    if (slides === null || missingSlide) return;
    const controller = new AbortController();
    async function loadSlide() {
      try {
        const response = assetId
          ? await documentsApi.imageAssetContent(documentId, assetId, { signal: controller.signal }, revision)
          : await documentsApi.presentationSlideContent(documentId, page, { signal: controller.signal }, revision);
        if (!response.ok) throw new Error(`The rendered slide could not be opened (${response.status}).`);
        const buffer = await response.arrayBuffer();
        if (!controller.signal.aborted) {
          setFailure(null);
          setSlide({ key: requestKey, buffer, contentType: response.headers.get("Content-Type") ?? "image/png" });
        }
      } catch (loadError) {
        if (!controller.signal.aborted) setFailure({ key: requestKey, message: readableError(loadError, "The rendered slide could not be opened.") });
      }
    }
    void loadSlide();
    return () => controller.abort();
  }, [assetId, documentId, page, requestKey, slides, missingSlide, revision]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (shouldIgnoreViewerShortcut(event) || !slides?.length) return;
      const next = event.key === "ArrowLeft" ? slides[index - 1] : event.key === "ArrowRight" ? slides[index + 1] : undefined;
      if (next !== undefined) {
        event.preventDefault();
        setPage(next);
      } else if (event.key.toLowerCase() === "c" && citedPage !== null && slides.includes(citedPage)) {
        event.preventDefault();
        setPage(citedPage);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [slides, index, citedPage]);

  return (
    <div className="source-viewer-document" aria-busy={loading}>
      <div className="source-viewer-toolbar">
        <div className="source-viewer-page-controls" aria-label="Slide navigation">
          <button type="button" disabled={index <= 0} onClick={() => setPage(slides![index - 1])} aria-label="Previous slide">
            <ChevronLeft aria-hidden="true" size={16} /><span className="source-viewer-control-text">Previous</span>
          </button>
          <label className="source-viewer-slide-selector">
            Slide
            <select aria-label="Slide number" value={page} disabled={!slides?.length} onChange={(event) => setPage(Number(event.target.value))}>
              {index < 0 ? <option value={page}>{page}</option> : null}
              {slides?.map((number) => <option key={number} value={number}>{number}</option>)}
            </select>
          </label>
          <span aria-live="polite">{slides ? `${index >= 0 ? index + 1 : "—"} of ${slides.length}` : "Loading slides"}</span>
          <button type="button" disabled={!slides?.length || index >= slides.length - 1} onClick={() => setPage(slides![index + 1])} aria-label="Next slide">
            <span className="source-viewer-control-text">Next</span><ChevronRight aria-hidden="true" size={16} />
          </button>
        </div>
        <div className="source-viewer-toolbar-end">
          {citedPage !== null && page !== citedPage ? (
            <button className="source-viewer-jump" type="button" disabled={!slides?.includes(citedPage)} onClick={() => setPage(citedPage)}>
              <RotateCcw aria-hidden="true" size={15} />Return to cited slide
            </button>
          ) : null}
          {toolbarEnd}
        </div>
      </div>
      {loading ? <SourceViewerLoading /> : null}
      {error ? <SourceViewerError title="Slide preview unavailable" message={error}
        guidance="Retry the preview. If it is still unavailable, reingest the presentation from Documents to regenerate its slides."
        action={<button className="sv-action-primary" type="button" onClick={() => { setCatalogError(null); setAttempt((value) => value + 1); }}>Retry preview</button>} /> : null}
      {slide ? (
        <div className="source-viewer-pptx-content" hidden={loading || error !== null}>
          <ImageRegionDocument buffer={slide.buffer} contentType={slide.contentType}
            fallbackMessage={citedPage === page ? fallbackMessage : ""} regions={slideRegions} sourceLabel={`Slide ${page}`}
            onImageError={() => setFailure({ key: slide.key, message: "The slide image could not be displayed." })} />
        </div>
      ) : null}
    </div>
  );
}
