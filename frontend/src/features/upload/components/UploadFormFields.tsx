import { useEffect, useState, type JSX } from "react";
import { Plus, Share2, X } from "lucide-react";
import { clearanceLevelDescription, clearanceLevelLabel } from "@/lib/auth/authz";
import type { ClearanceLevel } from "@/types/api";

export function SelectField({ disabled, emptyLabel, helper, label, onChange, options, value }: SelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">{label}</span>
      <select disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} className="sv-select">
        {options.map((option) => <option key={option || "empty"} value={option}>{option || emptyLabel || option}</option>)}
      </select>
      {helper ? <small className="text-secondary">{helper}</small> : null}
    </label>
  );
}

export function ClearanceSelect({ disabled, onChange, options, value }: ClearanceSelectProps) {
  return (
    <label className="sv-field">
      <span className="sv-label">Clearance Level</span>
      <select disabled={disabled} value={value} onChange={(event) => onChange(event.target.value as ClearanceLevel)} className="sv-select">
        {options.map((option) => <option key={option} value={option}>{clearanceLevelLabel(option)}</option>)}
      </select>
      <small className="text-secondary">{clearanceLevelDescription(value)}</small>
    </label>
  );
}

export function SharedSpacesField({ disabled, onAdd, onRemove, options, values }: SharedSpacesFieldProps) {
  const [candidate, setCandidate] = useState("");
  const canAdd = Boolean(candidate) && !disabled;

  useEffect(() => {
    if (candidate && !options.includes(candidate)) setCandidate("");
  }, [candidate, options]);

  function addCandidate() {
    if (!canAdd) return;
    onAdd(candidate);
    setCandidate("");
  }

  return (
    <div className="sv-field md:col-span-2">
      <span className="sv-label">Shared Knowledge Spaces <span className="font-normal text-secondary">(optional)</span></span>
      {values.length ? (
        <div className="knowledge-topic-chips">
          {values.map((path) => (
            <span key={path} className="sv-pill knowledge-topic-pill">
              {path}
              <button type="button" onClick={() => onRemove(path)} disabled={disabled} aria-label={`Remove ${path}`}>
                <X size={13} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="knowledge-topic-form">
        <select
          aria-label="Shared Knowledge Space"
          className="sv-select"
          disabled={disabled || options.length === 0}
          onChange={(event) => setCandidate(event.target.value)}
          value={candidate}
        >
          <option value="">{options.length ? "Select shared space" : "No eligible shared spaces"}</option>
          {options.map((path) => <option key={path} value={path}>{path}</option>)}
        </select>
        <button type="button" className="sv-action-secondary" disabled={!canAdd} onClick={addCandidate}>
          <Plus size={15} /> Add
        </button>
      </div>
      <small className="text-secondary"><Share2 size={12} className="inline align-[-2px]" /> Selected spaces receive read access when the document is indexed.</small>
    </div>
  );
}

export function Guardrail({ detail, icon, title }: { detail: string; icon: JSX.Element; title: string }) {
  return (
    <div className="upload-guardrail">
      <div className="flex items-center gap-2 text-body-md font-bold text-on-surface"><span className="text-primary">{icon}</span>{title}</div>
      <p className="mt-1 text-body-md text-on-surface-variant">{detail}</p>
    </div>
  );
}

export type SelectProps = { disabled?: boolean; emptyLabel?: string; helper?: string; label: string; onChange: (value: string) => void; options: string[]; value: string };

export type ClearanceSelectProps = { disabled?: boolean; onChange: (value: ClearanceLevel) => void; options: ClearanceLevel[]; value: ClearanceLevel };

export type SharedSpacesFieldProps = { disabled?: boolean; onAdd: (path: string) => void; onRemove: (path: string) => void; options: string[]; values: string[] };
