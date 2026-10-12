import { useBranding } from "./BrandContext";

const Prudentia_SYMBOL_DARK = "/brand/Prudentia-symbol-dark-transparent.png";
const Prudentia_SYMBOL_LIGHT = "/brand/Prudentia-symbol-light-transparent.png";

type BrandAssetProps = {
  className?: string;
  label?: string;
};

export function PrudentiaBrandMark({ className, label }: BrandAssetProps) {
  const branding = useBranding();
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={classNames("Prudentia-brand-asset Prudentia-brand-mark", className)}
      role={label ? "img" : undefined}
    >
      {branding.logo_url ? <img className="Prudentia-brand-art" src={branding.logo_url} alt="" aria-hidden="true" draggable="false" /> : <>
        <img className="Prudentia-brand-art Prudentia-brand-art-dark" src={Prudentia_SYMBOL_DARK} alt="" aria-hidden="true" draggable="false" />
        <img className="Prudentia-brand-art Prudentia-brand-art-light" src={Prudentia_SYMBOL_LIGHT} alt="" aria-hidden="true" draggable="false" />
      </>}
    </span>
  );
}

export function PrudentiaWordmark({ className, label }: BrandAssetProps) {
  const branding = useBranding();
  const accessibleLabel = label ?? branding.app_name;
  return (
    <span
      aria-label={accessibleLabel}
      className={classNames("Prudentia-brand-asset Prudentia-brand-wordmark", className)}
      role="img"
    >
      <PrudentiaBrandMark className="Prudentia-wordmark-mark" />
      <span className="Prudentia-wordmark-text" aria-hidden="true">
        {branding.app_name}
      </span>
    </span>
  );
}

function classNames(...values: Array<string | undefined>): string {
  return values.filter(Boolean).join(" ");
}
