import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageUp } from "lucide-react";

import { BrandProvider, defaultBranding } from "@/components/brand/BrandContext";
import { PrudentiaBrandMark } from "@/components/brand/PrudentiaBrand";
import { adminApi, type WorkspaceBrandingRequest } from "@/lib/api/contracts";
import { errorMessage } from "@/lib/utils/format";
import { contrastRatio, isHexColor, readableForeground, readableThemeColor, themeCanvasColor, type UiTheme, DARK_TEXT } from "@/lib/utils/themeContrast";
import type { WorkspaceBranding } from "@/types/api";

export function BrandingPanel({ notify }: { notify: (message: { title: string; description: string; tone: "error" | "success" | "warning" }) => void }) {
  const queryClient = useQueryClient();
  const logoInputRef = useRef<HTMLInputElement>(null);
  const brandingQuery = useQuery({ queryKey: ["branding"], queryFn: adminApi.getBranding, retry: false });
  const [draft, setDraft] = useState<WorkspaceBrandingRequest>({ app_name: defaultBranding.app_name, primary_color: defaultBranding.primary_color, accent_color: defaultBranding.accent_color, background_color: defaultBranding.background_color, login_message: defaultBranding.login_message, support_url: defaultBranding.support_url, theme_mode: defaultBranding.theme_mode, h1_size: defaultBranding.h1_size, h1_weight: defaultBranding.h1_weight, h1_color: defaultBranding.h1_color, h2_size: defaultBranding.h2_size, h2_weight: defaultBranding.h2_weight, h2_color: defaultBranding.h2_color, body_size: defaultBranding.body_size });
  const [selectedLogoName, setSelectedLogoName] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: adminApi.updateBranding,
    onSuccess: (branding) => saved(branding, "Branding saved"),
    onError: (error) => fail(error, "Branding could not be saved."),
  });
  const upload = useMutation({
    mutationFn: adminApi.uploadBrandLogo,
    onSuccess: (branding) => saved(branding, "Logo uploaded"),
    onError: (error) => fail(error, "Logo could not be uploaded."),
  });
  const removeLogo = useMutation({
    mutationFn: adminApi.deleteBrandLogo,
    onSuccess: (branding) => saved(branding, "Custom logo removed"),
    onError: (error) => fail(error, "Logo could not be removed."),
  });
  const reset = useMutation({
    mutationFn: adminApi.resetBranding,
    onSuccess: (branding) => saved(branding, "Default branding restored"),
    onError: (error) => fail(error, "Branding could not be restored."),
  });

  useEffect(() => {
    if (brandingQuery.data) setDraft(requestFromBranding(brandingQuery.data));
  }, [brandingQuery.data]);

  function saved(branding: WorkspaceBranding, title: string) {
    queryClient.setQueryData(["branding"], branding);
    setDraft(requestFromBranding(branding));
    notify({ title, description: "The change is visible across the workspace now.", tone: "success" });
  }

  function fail(error: Error, fallback: string) {
    notify({ title: "Branding update failed", description: errorMessage(error, fallback), tone: "error" });
  }

  function chooseLogo(file: File | undefined) {
    if (!file) return;
    setSelectedLogoName(file.name);
    upload.mutate(file);
  }

  return (
    <section className="rounded border border-surface-border bg-surface-container-low p-4" aria-labelledby="branding-title">
      <div className="mb-4">
        <h2 id="branding-title" className="text-title-md">Workspace branding</h2>
        <p className="mt-1 text-body-md text-secondary">Only Platform Admins can change workspace branding, theme, and typography.</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-1 xl:grid-cols-[minmax(0,1fr)_26rem]">
        <div className="grid gap-4">
          <label className="sv-field">
            <span className="sv-label">Application name</span>
            <input className="sv-input" value={draft.app_name} maxLength={80} onChange={(event) => setDraft({ ...draft, app_name: event.target.value })} />
          </label>
          <label className="sv-field">
            <span className="sv-label">Primary color</span>
            <span className="flex items-center gap-2"><input aria-label="Primary color picker" type="color" value={draft.primary_color} onChange={(event) => setDraft({ ...draft, primary_color: event.target.value.toUpperCase() })} /><input className="sv-input" value={draft.primary_color} pattern="^#[0-9A-Fa-f]{6}$" onChange={(event) => setDraft({ ...draft, primary_color: event.target.value })} /></span>
            <PrimaryContrastNote color={draft.primary_color} />
          </label>
          <label className="sv-field">
            <span className="sv-label">Accent color</span>
            <span className="flex items-center gap-2"><input aria-label="Accent color picker" type="color" value={draft.accent_color} onChange={(event) => setDraft({ ...draft, accent_color: event.target.value.toUpperCase() })} /><input className="sv-input" value={draft.accent_color} pattern="^#[0-9A-Fa-f]{6}$" onChange={(event) => setDraft({ ...draft, accent_color: event.target.value })} /></span>
            <ThemeColorNote color={draft.accent_color} label="Accent text" />
          </label>
          <label className="sv-field">
            <span className="sv-label">Theme background</span>
            <span className="flex items-center gap-2"><input aria-label="Workspace background picker" type="color" value={draft.background_color} onChange={(event) => setDraft({ ...draft, background_color: event.target.value.toUpperCase() })} /><input className="sv-input" value={draft.background_color} pattern="^#[0-9A-Fa-f]{6}$" onChange={(event) => setDraft({ ...draft, background_color: event.target.value })} /></span>
            <span className="text-body-md text-secondary">Applies a controlled tint to both light and dark canvas surfaces while keeping text readable.</span>
          </label>
          <label className="sv-field">
            <span className="sv-label">Sign-in message</span>
            <textarea className="sv-input min-h-20" value={draft.login_message} maxLength={240} onChange={(event) => setDraft({ ...draft, login_message: event.target.value })} />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="sv-field"><span className="sv-label">Support URL (optional)</span><input className="sv-input" type="url" value={draft.support_url ?? ""} onChange={(event) => setDraft({ ...draft, support_url: event.target.value || null })} /></label>
            <label className="sv-field"><span className="sv-label">Theme access</span><select className="sv-input" value={draft.theme_mode} onChange={(event) => setDraft({ ...draft, theme_mode: event.target.value as WorkspaceBrandingRequest["theme_mode"] })}><option value="user">Let users choose</option><option value="light">Force light</option><option value="dark">Force dark</option></select></label>
          </div>
          <fieldset className="grid gap-4 rounded border border-surface-border p-3">
            <legend className="px-1 text-label-md font-bold text-on-surface">Workspace typography</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="sv-field"><span className="sv-label">H1 size</span><select className="sv-input" value={draft.h1_size} onChange={(event) => setDraft({ ...draft, h1_size: event.target.value as WorkspaceBrandingRequest["h1_size"] })}><option value="compact">Compact</option><option value="standard">Standard</option><option value="large">Large</option></select></label>
              <label className="sv-field"><span className="sv-label">H1 weight</span><select className="sv-input" value={draft.h1_weight} onChange={(event) => setDraft({ ...draft, h1_weight: event.target.value as WorkspaceBrandingRequest["h1_weight"] })}><option value="semibold">Semibold</option><option value="bold">Bold</option><option value="extrabold">Extra bold</option></select></label>
              <ColorOverride label="H1 color" value={draft.h1_color} fallback={draft.primary_color} onChange={(value) => setDraft({ ...draft, h1_color: value })} />
              <label className="sv-field"><span className="sv-label">H2 size</span><select className="sv-input" value={draft.h2_size} onChange={(event) => setDraft({ ...draft, h2_size: event.target.value as WorkspaceBrandingRequest["h2_size"] })}><option value="compact">Compact</option><option value="standard">Standard</option><option value="large">Large</option></select></label>
              <label className="sv-field"><span className="sv-label">H2 weight</span><select className="sv-input" value={draft.h2_weight} onChange={(event) => setDraft({ ...draft, h2_weight: event.target.value as WorkspaceBrandingRequest["h2_weight"] })}><option value="semibold">Semibold</option><option value="bold">Bold</option><option value="extrabold">Extra bold</option></select></label>
              <ColorOverride label="H2 color" value={draft.h2_color} fallback={draft.primary_color} onChange={(value) => setDraft({ ...draft, h2_color: value })} />
            </div>
            <label className="sv-field"><span className="sv-label">Body text size</span><select className="sv-input" value={draft.body_size} onChange={(event) => setDraft({ ...draft, body_size: event.target.value as WorkspaceBrandingRequest["body_size"] })}><option value="compact">Compact</option><option value="standard">Standard</option><option value="large">Large</option></select></label>
          </fieldset>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="sv-action-primary" disabled={!validBrandingDraft(draft) || save.isPending} onClick={() => save.mutate({ ...draft, app_name: draft.app_name.trim(), login_message: draft.login_message.trim() })}>Save and apply</button>
            <button type="button" className="sv-action-secondary" disabled={reset.isPending} onClick={() => reset.mutate()}>Restore defaults</button>
          </div>
          <div className="border-t border-surface-border pt-4">
            <input ref={logoInputRef} id="workspace-logo" className="sr-only" type="file" accept="image/png,image/jpeg" onChange={(event) => { chooseLogo(event.target.files?.[0]); event.currentTarget.value = ""; }} />
            <div className="flex flex-wrap items-center gap-3 rounded border border-dashed border-surface-border bg-surface-card p-3">
              <span className="flex h-9 w-9 items-center justify-center rounded bg-primary/10 text-primary" aria-hidden="true"><ImageUp size={18} /></span>
              <div className="min-w-0 flex-1">
                <p className="text-label-md font-bold text-on-surface">{selectedLogoName ?? (brandingQuery.data?.logo_url ? "Custom logo active" : "Use a custom logo")}</p>
                <p className="text-body-md text-secondary">PNG or JPEG, up to 1 MB. It replaces the logo immediately after upload.</p>
              </div>
              <button type="button" className="sv-action-secondary" disabled={upload.isPending} onClick={() => logoInputRef.current?.click()}>{upload.isPending ? "Uploading…" : brandingQuery.data?.logo_url ? "Replace logo" : "Choose file"}</button>
              {brandingQuery.data?.logo_url ? <button type="button" className="sv-action-secondary" disabled={removeLogo.isPending} onClick={() => removeLogo.mutate()}>Use default</button> : null}
            </div>
          </div>
        </div>
          <div className="rounded border border-surface-border bg-surface-card p-4">
            <p className="sv-eyebrow">Live preview</p>
            <BrandProvider value={{ ...defaultBranding, ...draft, logo_url: brandingQuery.data?.logo_url ?? null, updated_at: null }}>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {(["light", "dark"] as const).map((theme) => <BrandingPreview key={theme} draft={draft} theme={theme} />)}
              </div>
            </BrandProvider>
          </div>
      </div>
    </section>
  );
}

function requestFromBranding(branding: WorkspaceBranding): WorkspaceBrandingRequest {
  const { logo_url: _logoUrl, updated_at: _updatedAt, ...request } = branding;
  return request;
}

function ColorOverride({ fallback, label, onChange, value }: { fallback: string; label: string; onChange: (value: string | null) => void; value: string | null }) {
  return <label className="sv-field"><span className="sv-label">{label}</span><span className="flex items-center gap-2"><input aria-label={`${label} picker`} type="color" value={value ?? fallback} onChange={(event) => onChange(event.target.value.toUpperCase())} /><input className="sv-input" aria-label={`${label} hex value`} placeholder="Theme default" value={value ?? ""} pattern="^#[0-9A-Fa-f]{6}$" onChange={(event) => onChange(event.target.value || null)} /></span><ThemeColorNote color={value} label="Resolved text" /><span className="text-body-md text-secondary">Unreadable custom text colors fall back to the active theme text color.</span><button type="button" className="w-fit text-label-md text-primary underline" disabled={!value} onClick={() => onChange(null)}>Use theme default</button></label>;
}

function PrimaryContrastNote({ color }: { color: string }) {
  const primary = isHexColor(color) ? color : defaultBranding.primary_color;
  const foreground = readableForeground(primary);
  return <span className="text-body-md text-secondary">Button text resolves to {foreground} ({contrastRatio(primary, foreground).toFixed(1)}:1 contrast).</span>;
}

function ThemeColorNote({ color, label }: { color: string | null; label: string }) {
  return <span className="text-body-md text-secondary">{label}: light {readableThemeColor(color, "light")}; dark {readableThemeColor(color, "dark")}.</span>;
}

export function validBrandingDraft(draft: WorkspaceBrandingRequest): boolean {
  return Boolean(draft.app_name.trim() && draft.login_message.trim() && /^#[0-9A-Fa-f]{6}$/.test(draft.primary_color) && /^#[0-9A-Fa-f]{6}$/.test(draft.accent_color) && /^#[0-9A-Fa-f]{6}$/.test(draft.background_color) && optionalHex(draft.h1_color) && optionalHex(draft.h2_color));
}

function optionalHex(value: string | null) {
  return value === null || /^#[0-9A-Fa-f]{6}$/.test(value);
}

const TYPE_SIZES = {
  h1: { compact: "1.375rem", standard: "1.5rem", large: "1.75rem" },
  h2: { compact: "0.875rem", standard: "0.95rem", large: "1.125rem" },
  body: { compact: "0.8125rem", standard: "0.875rem", large: "1rem" },
} as const;
const TYPE_WEIGHTS = { semibold: "600", bold: "700", extrabold: "800" } as const;

function typographySize(role: keyof typeof TYPE_SIZES, value: "compact" | "standard" | "large") {
  return TYPE_SIZES[role][value];
}

function typographyWeight(value: "semibold" | "bold" | "extrabold") {
  return TYPE_WEIGHTS[value];
}

function BrandingPreview({ draft, theme }: { draft: WorkspaceBrandingRequest; theme: UiTheme }) {
  const light = theme === "light";
  const primary = isHexColor(draft.primary_color) ? draft.primary_color : defaultBranding.primary_color;
  const background = themeCanvasColor(draft.background_color, theme);
  const text = light ? DARK_TEXT : "#F7F6F8";
  return (
    <div className="branding-preview rounded border p-3" data-theme={theme} style={{
      "--color-primary": readableThemeColor(primary, theme),
      "--color-primary-action": primary,
      "--color-brand-primary": draft.primary_color,
      "--color-brand-accent": readableThemeColor(draft.accent_color, theme),
      "--color-brand-background": isHexColor(draft.background_color) ? draft.background_color : defaultBranding.background_color,
      "--color-background": background,
      "--app-bg": background,
      "--app-root-bg": background,
      "--color-on-primary": readableForeground(primary),
      "--color-on-surface": text,
      "--color-on-surface-variant": light ? "#4F5560" : "#D4D1DB",
      "--color-secondary": light ? "#4F5560" : "#D4D1DB",
      "--color-surface": light ? "#FCFCFC" : "#24242B",
      "--color-surface-card": light ? "#FFFFFF" : "#222228",
      "--color-surface-container-low": light ? "#F2F2F5" : "#2A2A32",
      "--color-surface-container-high": light ? "#E9E9EE" : "#35353E",
      "--color-surface-border": light ? "#858A95" : "#5E5E6C",
      "--color-heading-h1": readableThemeColor(draft.h1_color, theme),
      "--color-heading-h2": readableThemeColor(draft.h2_color, theme),
      "--color-primary-foreground": readableThemeColor(primary, theme),
      "--focus-ring": readableThemeColor(draft.accent_color, theme),
      "--font-size-ui-page-title": typographySize("h1", draft.h1_size),
      "--font-weight-ui-page-title": typographyWeight(draft.h1_weight),
      "--font-size-ui-section": typographySize("h2", draft.h2_size),
      "--font-weight-ui-section": typographyWeight(draft.h2_weight),
      "--font-size-ui-body": typographySize("body", draft.body_size),
      background: "var(--color-background)",
      color: text,
    } as CSSProperties}>
      <p className="sv-eyebrow">{theme} mode</p>
      <div className="mt-2 flex items-center gap-3"><PrudentiaBrandMark /><strong className="break-words text-label-md">{draft.app_name || "Application name"}</strong></div>
      <h1 className="mt-4 sv-page-title">Workspace title</h1>
      <h2 className="mt-3 sv-section-title">Section heading</h2>
      <p className="mt-2 text-body-md text-secondary">{draft.login_message || "Sign-in message"}</p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="rounded border px-2 py-1 text-label-md" style={{ borderColor: primary, backgroundColor: `color-mix(in srgb, ${primary} 12%, transparent)` }}>Selected navigation</span>
        <button type="button" className="sv-action-primary">Primary action</button>
        <a className="text-label-md underline" style={{ color: "var(--color-brand-accent)" }} href={draft.support_url ?? "#support"}>Support link</a>
        <span className="rounded px-1 text-label-md" style={{ outline: "3px solid var(--focus-ring)", outlineOffset: "2px" }}>Keyboard focus</span>
      </div>
    </div>
  );
}
