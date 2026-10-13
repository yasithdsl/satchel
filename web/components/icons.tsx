import type { ReactNode } from "react";

function Svg({
  children,
  className = "h-6 w-6",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

type IconProps = { className?: string };

export function LedgerIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="5" y="2.5" width="14" height="19" rx="2.5" />
      <rect x="7.5" y="5" width="9" height="11" rx="1" />
      <path d="M10 19h4" />
    </Svg>
  );
}

export function HeadphonesIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 14v-2a8 8 0 0 1 16 0v2" />
      <rect x="3" y="14" width="4.5" height="6.5" rx="1.5" />
      <rect x="16.5" y="14" width="4.5" height="6.5" rx="1.5" />
    </Svg>
  );
}

export function LaptopIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="4.5" y="5" width="15" height="10" rx="1.5" />
      <path d="M2.5 19h19l-1.5-4h-16z" />
    </Svg>
  );
}

export function KitchenIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 10h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z" />
      <path d="M17 12h1.5a2 2 0 0 1 0 4H17" />
      <path d="M8 3.5c0 1.5 1.5 1.5 1.5 3M12 3.5c0 1.5 1.5 1.5 1.5 3" />
    </Svg>
  );
}

export function PlugIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M9 3v5M15 3v5" />
      <path d="M6 8h12v3a6 6 0 0 1-12 0z" />
      <path d="M12 17v4" />
    </Svg>
  );
}

export function BagIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M5 8h14l-1 12H6z" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2" />
    </Svg>
  );
}

export function CategoryIcon({
  category,
  className,
}: {
  category: string | null | undefined;
  className?: string;
}) {
  switch ((category ?? "").toLowerCase()) {
    case "headphones":
    case "audio":
      return <HeadphonesIcon className={className} />;
    case "laptops":
    case "laptop":
      return <LaptopIcon className={className} />;
    case "kitchen":
      return <KitchenIcon className={className} />;
    case "accessories":
      return <PlugIcon className={className} />;
    default:
      return <BagIcon className={className} />;
  }
}

export function AgentIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="5" y="8" width="14" height="11" rx="3" />
      <path d="M12 8V4.5" />
      <circle cx="12" cy="3.5" r="1" />
      <circle cx="9.5" cy="13" r="1" />
      <circle cx="14.5" cy="13" r="1" />
      <path d="M3 12v3M21 12v3" />
    </Svg>
  );
}

export function VaultIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="3.5" y="4" width="17" height="15" rx="2" />
      <circle cx="12" cy="11.5" r="3.5" />
      <path d="M12 8v1M12 14v1M8.5 11.5h1M14.5 11.5h1" />
      <path d="M6 19v1.5M18 19v1.5" />
    </Svg>
  );
}

export function SignerIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M15.5 4.5l4 4L9 19H5v-4z" />
      <path d="M13.5 6.5l4 4" />
    </Svg>
  );
}

export function NetworkIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="3" y="4" width="7" height="7" rx="1.5" />
      <rect x="14" y="4" width="7" height="7" rx="1.5" />
      <rect x="8.5" y="14" width="7" height="7" rx="1.5" />
      <path d="M10 7.5h4M7 11l3 3M17 11l-3 3" />
    </Svg>
  );
}

export function AttackerIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 10c0-4 3.5-6.5 8-6.5s8 2.5 8 6.5c0 3-1.5 4.5-3 5.5V20H7v-4.5C5.5 14.5 4 13 4 10z" />
      <path d="M8 11.5l2.5 1M16 11.5l-2.5 1" />
      <path d="M10 20v-2M14 20v-2" />
    </Svg>
  );
}

export function CheckIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Svg>
  );
}

export function ShieldIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M12 3l7 3v5.5c0 4.5-3 8-7 9.5-4-1.5-7-5-7-9.5V6z" />
    </Svg>
  );
}

export function KeyIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="8" cy="12" r="4" />
      <path d="M12 12h9M18 12v3M15 12v2" />
    </Svg>
  );
}

export function SearchIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.2-4.2" />
    </Svg>
  );
}

export function XIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
  );
}

export function ArrowIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4 12h15M14 7l5 5-5 5" />
    </Svg>
  );
}

export function SatchelIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path d="M4.5 9.5h15l-1.2 10h-12.6z" />
      <path d="M8.5 9.5V7.5a3.5 3.5 0 0 1 7 0v2" />
      <path d="M4.5 13h15" />
      <rect x="10.5" y="11.6" width="3" height="2.8" rx="0.6" />
    </Svg>
  );
}

export function LockIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <rect x="5" y="10.5" width="14" height="10" rx="2" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    </Svg>
  );
}
