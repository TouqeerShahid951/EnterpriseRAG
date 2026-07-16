import { Boxes, Cpu, ServerCog } from "lucide-react";

import { Fact } from "@/components/layout/Common";

export type ConfigPanel = "models" | "services" | "workers";

export function ConfigPanelTabs({ onChange, value }: { value: ConfigPanel; onChange: (value: ConfigPanel) => void }) {
  const items: Array<{
    id: ConfigPanel;
    label: string;
    description: string;
    icon: React.ReactNode;
  }> = [
    {
      id: "models",
      label: "Model Routing",
      description: "Choose the stack, assign role models, test the draft, and activate it.",
      icon: <ServerCog size={18} />,
    },
    {
      id: "services",
      label: "vLLM Services",
      description: "Check provider availability, tune vLLM limits, and restart one service at a time.",
      icon: <Boxes size={18} />,
    },
    {
      id: "workers",
      label: "Ingestion Controls",
      description: "Tune ingestion capacity, OCR review gates, and enrichment behavior.",
      icon: <Cpu size={18} />,
    },
  ];

  return (
    <nav aria-label="Runtime Settings sections" className="grid gap-2 lg:grid-cols-3">
      {items.map((item) => {
        const active = value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            aria-current={active ? "page" : undefined}
            onClick={() => onChange(item.id)}
            className={`min-h-20 rounded border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
              active
                ? "border-primary bg-primary/10 text-on-surface"
                : "border-surface-border bg-surface-container-low text-on-surface hover:bg-surface-container-high"
            }`}
          >
            <span className={`flex items-center gap-2 text-label-md font-bold ${active ? "text-primary" : "text-on-surface"}`}>
              {item.icon}
              {item.label}
            </span>
            <span className="mt-1 block text-body-md text-secondary">{item.description}</span>
          </button>
        );
      })}
    </nav>
  );
}

export function RuntimeStatusStrip({
  activeStack,
  configurationSource,
  discoveryState,
  draftState,
  restartRequirement,
}: RuntimeStatusStripProps) {
  return (
    <section className="rounded border border-surface-border bg-surface-container-low p-3" aria-label="Runtime Settings status">
      <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <Fact label="Active stack" value={activeStack} />
        <Fact label="Configuration source" value={configurationSource} />
        <Fact label="Draft state" value={draftState} />
        <Fact label="Model discovery" value={discoveryState} />
        <Fact label="Restart requirement" value={restartRequirement} />
      </dl>
    </section>
  );
}

type RuntimeStatusStripProps = {
  activeStack: string;
  configurationSource: string;
  discoveryState: string;
  draftState: string;
  restartRequirement: string;
};
