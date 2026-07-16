import { Cpu, Save } from "lucide-react";

import { Fact, InlineMessage } from "@/components/layout/Common";
import {
  labelize,
  pdfImageReviewThresholdLabel,
  thresholdPercentFromConfig,
} from "@/features/settings/models/settingsLabels";
import type { IngestConfig } from "@/types/api";
import { errorMessage } from "@/lib/utils/format";

type Props = {
  config?: IngestConfig;
  configError: Error | null;
  configFailed: boolean;
  graphEnrichmentEnabled: boolean;
  highConcurrencyConfirmed: boolean;
  isValid: boolean;
  ocrReviewThresholdPercent: number;
  pdfImageReviewThreshold: number;
  savePending: boolean;
  visionLayoutRepairEnabled: boolean;
  workerConcurrency: number;
  onGraphEnrichmentChange: (value: boolean) => void;
  onHighConcurrencyConfirmedChange: (value: boolean) => void;
  onOcrReviewThresholdChange: (value: number) => void;
  onPdfImageReviewThresholdChange: (value: number) => void;
  onSave: () => void;
  onVisionLayoutRepairChange: (value: boolean) => void;
  onWorkerConcurrencyChange: (value: number) => void;
};

export function IngestionControlsPanel({
  config,
  configError,
  configFailed,
  graphEnrichmentEnabled,
  highConcurrencyConfirmed,
  isValid,
  ocrReviewThresholdPercent,
  pdfImageReviewThreshold,
  savePending,
  visionLayoutRepairEnabled,
  workerConcurrency,
  onGraphEnrichmentChange,
  onHighConcurrencyConfirmedChange,
  onOcrReviewThresholdChange,
  onPdfImageReviewThresholdChange,
  onSave,
  onVisionLayoutRepairChange,
  onWorkerConcurrencyChange,
}: Props) {
  return (
    <section className="sv-card p-4">
      <div className="flex items-center gap-2">
        <Cpu size={18} className="text-primary" />
        <h2 className="text-headline-sm">Ingestion Controls</h2>
      </div>
      <p className="mt-2 text-body-md text-secondary">
        Capacity is per worker replica. One is recommended for this 8 GB Docker environment.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="sv-field">
          <span className="sv-label">Worker concurrency</span>
          <input
            type="number"
            min={1}
            max={10}
            value={workerConcurrency}
            onChange={(event) => onWorkerConcurrencyChange(Number(event.target.value))}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">Allowed range: 1-10. Recommended: 1.</span>
        </label>
        <label className="sv-field">
          <span className="sv-label">OCR review threshold</span>
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={ocrReviewThresholdPercent}
            onChange={(event) => onOcrReviewThresholdChange(Number(event.target.value))}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">
            OCR blocks below this confidence percentage pause for review. Current target: below {ocrReviewThresholdPercent || 0}%.
          </span>
        </label>
        <label className="sv-field">
          <span className="sv-label">PDF image review threshold</span>
          <input
            type="number"
            min={0}
            max={10000}
            step={1}
            value={pdfImageReviewThreshold}
            onChange={(event) => onPdfImageReviewThresholdChange(Number(event.target.value))}
            className="sv-input"
          />
          <span className="text-body-md text-secondary">
            Pause for review when selected PDF image candidates exceed this count. Set 0 to skip this review gate.
          </span>
        </label>
        <ToggleSetting
          checked={visionLayoutRepairEnabled}
          description="Use the vision model to re-read complex PDF pages after Docling. Keep off for faster bulk ingestion."
          label="Vision layout repair"
          onChange={onVisionLayoutRepairChange}
        />
        <ToggleSetting
          checked={graphEnrichmentEnabled}
          description="Show the Enrich graph action for completed documents. Keep off for faster bulk ingestion."
          label="Graph enrichment"
          onChange={onGraphEnrichmentChange}
        />
        {config ? <IngestionRuntimeFacts config={config} /> : null}
      </div>
      {!isValid ? (
        <InlineMessage tone="error">
          Worker concurrency must be 1-10, OCR review threshold must be 0-100%, and PDF image review threshold must be 0-10000.
        </InlineMessage>
      ) : null}
      {workerConcurrency > 2 ? (
        <InlineMessage tone="warning">Concurrency above 2 can exhaust memory when Docling parses multiple documents.</InlineMessage>
      ) : null}
      {workerConcurrency > 4 ? (
        <label className="mt-3 flex items-start gap-2 text-body-md">
          <input
            type="checkbox"
            checked={highConcurrencyConfirmed}
            onChange={(event) => onHighConcurrencyConfirmedChange(event.target.checked)}
          />
          I understand that this setting is hazardous for the current 8 GB Docker allocation.
        </label>
      ) : null}
      <div className="mt-4">
        <button
          type="button"
          className="sv-action-primary"
          disabled={!isValid || (workerConcurrency > 4 && !highConcurrencyConfirmed) || savePending}
          onClick={onSave}
        >
          <Save size={16} />
          {savePending ? "Applying" : "Save ingestion controls"}
        </button>
      </div>
      {configFailed ? <InlineMessage tone="error">{errorMessage(configError, "Unable to load ingestion controls.")}</InlineMessage> : null}
    </section>
  );
}

function ToggleSetting({ checked, description, label, onChange }: {
  checked: boolean;
  description: string;
  label: string;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 rounded border border-subtle bg-surface-muted/40 p-3 text-body-md">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="mt-1" />
      <span>
        <span className="block text-label-md">{label}</span>
        <span className="block text-secondary">{description}</span>
      </span>
    </label>
  );
}

function IngestionRuntimeFacts({ config }: { config: IngestConfig }) {
  return (
    <dl className="grid grid-cols-2 gap-3">
      <Fact label="Worker" value={config.worker_online ? "Online" : "Offline"} />
      <Fact label="Apply status" value={labelize(config.apply_status)} />
      <Fact label="Observed pool" value={String(config.observed_pool_size)} />
      <Fact label="Active jobs" value={String(config.active_jobs)} />
      <Fact label="OCR review" value={`Below ${thresholdPercentFromConfig(config.ocr_review_confidence_threshold)}%`} />
      <Fact label="PDF image review" value={pdfImageReviewThresholdLabel(config.pdf_image_review_threshold)} />
      <Fact label="Vision repair" value={config.vision_layout_repair_enabled ? "On" : "Off"} />
      <Fact label="Graph enrichment" value={config.graph_enrichment_enabled ? "On" : "Off"} />
    </dl>
  );
}
