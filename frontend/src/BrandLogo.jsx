import { useId } from "react";

/**
 * Autoline circular wolf mark (SVG redraw of brand emblem).
 * @param {{ size?: number, className?: string, title?: string }} props
 */
export default function BrandLogo({ size = 28, className = "", title = "奥特莱" }) {
  const gradId = `autoline-grad-${useId().replace(/:/g, "")}`;
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={title}
      style={{ display: "block", flexShrink: 0 }}
    >
      <title>{title}</title>
      <defs>
        <linearGradient id={gradId} x1="32" y1="2" x2="32" y2="62" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0a3d7a" />
          <stop offset="50%" stopColor="#1565c0" />
          <stop offset="100%" stopColor="#1e88e5" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="30" fill={`url(#${gradId})`} />
      <path fill="#fff" d="M17 13l1.15 3.35L21.5 17.5l-3.35 1.15L17 22l-1.15-3.35L12.5 17.5l3.35-1.15z" />
      <path
        fill="#fff"
        opacity="0.95"
        d="M26.5 9.5l0.75 2.2L29.5 12.5l-2.25 0.75L26.5 15.5l-0.75-2.25L23.5 12.5l2.25-0.8z"
      />
      <path
        fill="#fff"
        opacity="0.9"
        d="M22 21l0.55 1.65L24.2 23.2l-1.65 0.55L22 25.4l-0.55-1.65L19.8 23.2l1.65-0.55z"
      />
      {/* Howling wolf head — snout toward upper-right */}
      <path
        fill="#fff"
        d="M30.2 20.5c2.4-4.2 7.2-6.8 12-6.2.4 2.2-.2 4.5-1.6 6.2 2.8.2 5.2 2.2 6.2 4.8.8 2.1.4 4.5-1 6.2-1 1.2-2.5 2-4.1 2.2.2 2.2-.8 4.4-2.6 5.6-1.6 1.1-3.7 1.3-5.5.6-.5 1.8-1.9 3.2-3.7 3.8-2.2.7-4.6.2-6.2-1.4-1.2-1.2-1.8-2.9-1.7-4.6-2-.6-3.6-2.1-4.4-4-.9-2.2-.4-4.8 1.2-6.5 1.2-1.3 2.9-2 4.7-2 .6-1.8 1.9-3.3 3.7-4.1zm4.2 10.2c-.95.15-1.6 1.05-1.45 2 .15.95 1.05 1.6 2 1.45.95-.15 1.6-1.05 1.45-2-.15-.95-1.05-1.6-2-1.45zm7.1 2.6c-.7.1-1.2.75-1.1 1.45.1.7.75 1.2 1.45 1.1.7-.1 1.2-.75 1.1-1.45-.1-.7-.75-1.2-1.45-1.1z"
      />
    </svg>
  );
}

export const BRAND_PRODUCT_NAME = "奥特莱 · 企业知识库";
