export type UiTheme = "light" | "dark";

export const DARK_TEXT = "#000000";
const LIGHT_TEXT = "#FFFFFF";
const DARK_SURFACE = "#24242B";
const LIGHT_SURFACE = "#FFFFFF";
const DARK_CANVAS = "#1B1B20";
const LIGHT_CANVAS = "#F7F6F8";

const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/;

export function isHexColor(value: string): boolean {
  return HEX_COLOR.test(value);
}

export function contrastRatio(first: string, second: string): number {
  if (!isHexColor(first) || !isHexColor(second)) return 0;
  const [lighter, darker] = [luminance(first), luminance(second)].sort((left, right) => right - left);
  return (lighter + 0.05) / (darker + 0.05);
}

export function readableForeground(background: string): string {
  if (!isHexColor(background)) return LIGHT_TEXT;
  return contrastRatio(background, DARK_TEXT) >= contrastRatio(background, LIGHT_TEXT)
    ? DARK_TEXT
    : LIGHT_TEXT;
}

export function readableThemeColor(color: string | null, theme: UiTheme): string {
  const fallback = theme === "light" ? DARK_TEXT : LIGHT_TEXT;
  const surface = theme === "light" ? LIGHT_SURFACE : DARK_SURFACE;
  if (!color || !isHexColor(color) || contrastRatio(color, surface) < 4.5) return fallback;
  return color.toUpperCase();
}

export function themeCanvasColor(color: string | null, theme: UiTheme): string {
  const fallback = theme === "light" ? LIGHT_CANVAS : DARK_CANVAS;
  if (!color || !isHexColor(color)) return fallback;
  const strength = theme === "light" ? 8 : 16;
  return `color-mix(in srgb, ${color.toUpperCase()} ${strength}%, ${fallback})`;
}

function luminance(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16);
  const [red, green, blue] = [value >> 16, (value >> 8) & 255, value & 255].map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}
