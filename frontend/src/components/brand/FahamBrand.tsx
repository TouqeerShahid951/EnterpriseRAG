const FAHAM_SYMBOL_DARK = "/brand/faham-symbol-dark.png";
const FAHAM_SYMBOL_LIGHT = "/brand/faham-symbol-light.png";
const FAHAM_WORDMARK_DARK = "/brand/faham-wordmark-dark.png";
const FAHAM_WORDMARK_LIGHT = "/brand/faham-wordmark-light.png";

type BrandAssetProps = {
  className?: string;
  label?: string;
};

export function FahamBrandMark({ className, label }: BrandAssetProps) {
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={classNames("faham-brand-asset faham-brand-mark", className)}
      role={label ? "img" : undefined}
    >
      <img className="faham-brand-art faham-brand-art-dark" src={FAHAM_SYMBOL_DARK} alt="" aria-hidden="true" draggable="false" />
      <img className="faham-brand-art faham-brand-art-light" src={FAHAM_SYMBOL_LIGHT} alt="" aria-hidden="true" draggable="false" />
    </span>
  );
}

export function FahamWordmark({ className, label = "Faham AI" }: BrandAssetProps) {
  return (
    <span
      aria-label={label}
      className={classNames("faham-brand-asset faham-brand-wordmark", className)}
      role="img"
    >
      <img className="faham-brand-art faham-brand-art-dark" src={FAHAM_WORDMARK_DARK} alt="" aria-hidden="true" draggable="false" />
      <img className="faham-brand-art faham-brand-art-light" src={FAHAM_WORDMARK_LIGHT} alt="" aria-hidden="true" draggable="false" />
    </span>
  );
}

function classNames(...values: Array<string | undefined>): string {
  return values.filter(Boolean).join(" ");
}
