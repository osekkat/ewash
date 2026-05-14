/* eslint-disable */
// ewash — icon set (lucide-inspired, all stroke-based)

// Note: rest is spread FIRST so our explicit attributes (especially
// stroke="currentColor") aren't clobbered if Babel-standalone leaks the
// numeric `stroke` prop or the custom `size` prop into rest.
const Icon = ({ d, size = 22, stroke = 1.8, fill = 'none', children, ...rest }) => (
  <svg {...rest} width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor"
    strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
    {d && <path d={d} />}
    {children}
  </svg>
);

const Icons = {
  // Navigation
  Home: (p) => <Icon {...p}><path d="M3 11l9-7 9 7v9a2 2 0 0 1-2 2h-4v-7H9v7H5a2 2 0 0 1-2-2z"/></Icon>,
  Calendar: (p) => <Icon {...p}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/></Icon>,
  Sparkle: (p) => <Icon {...p}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 17l.7 1.8L21.5 19.5l-1.8.7L19 22l-.7-1.8L16.5 19.5l1.8-.7z"/></Icon>,
  User: (p) => <Icon {...p}><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></Icon>,
  // UI
  ChevronLeft: (p) => <Icon {...p}><path d="M15 18l-6-6 6-6"/></Icon>,
  ChevronRight: (p) => <Icon {...p}><path d="M9 6l6 6-6 6"/></Icon>,
  ChevronDown: (p) => <Icon {...p}><path d="M6 9l6 6 6-6"/></Icon>,
  ChevronUp: (p) => <Icon {...p}><path d="M6 15l6-6 6 6"/></Icon>,
  Close: (p) => <Icon {...p}><path d="M6 6l12 12M18 6L6 18"/></Icon>,
  Check: (p) => <Icon {...p}><path d="M5 12l5 5L20 6"/></Icon>,
  CheckCircle: (p) => <Icon {...p}><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></Icon>,
  Plus: (p) => <Icon {...p}><path d="M12 5v14M5 12h14"/></Icon>,
  Minus: (p) => <Icon {...p}><path d="M5 12h14"/></Icon>,
  Search: (p) => <Icon {...p}><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></Icon>,
  Edit: (p) => <Icon {...p}><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></Icon>,
  More: (p) => <Icon {...p}><circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/></Icon>,
  Bell: (p) => <Icon {...p}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></Icon>,
  Settings: (p) => <Icon {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></Icon>,
  // Location & vehicle
  Pin: (p) => <Icon {...p}><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="3"/></Icon>,
  Navigation: (p) => <Icon {...p}><path d="M3 11l18-8-8 18-2-8z"/></Icon>,
  Car: (p) => <Icon {...p}><path d="M5 17h14M3 14l2-6h14l2 6"/><rect x="3" y="14" width="18" height="5" rx="1.5"/><circle cx="7.5" cy="18.5" r="1.4"/><circle cx="16.5" cy="18.5" r="1.4"/></Icon>,
  CarSide: (p) => <Icon {...p}><path d="M3 13l1.5-5h12l3 5"/><path d="M2 13h19v5H2z"/><circle cx="7" cy="18" r="1.5"/><circle cx="17" cy="18" r="1.5"/></Icon>,
  Moto: (p) => <Icon {...p}><circle cx="5" cy="17" r="3"/><circle cx="19" cy="17" r="3"/><path d="M5 17l5-7h4l3 4M14 10h4M9 10h4"/></Icon>,
  Suv: (p) => <Icon {...p}><path d="M3 16l1-7h14l3 7"/><rect x="2" y="16" width="20" height="4" rx="1.5"/><circle cx="7" cy="20" r="1.4"/><circle cx="17" cy="20" r="1.4"/></Icon>,
  // Brand / eco
  Drop: (p) => <Icon {...p}><path d="M12 3s7 7.5 7 12a7 7 0 0 1-14 0c0-4.5 7-12 7-12z"/></Icon>,
  Leaf: (p) => <Icon {...p}><path d="M20 4S8 4 5 11s3 9 8 9c5 0 9-3 9-9 0-3-2-7-2-7z"/><path d="M5 19c4-5 9-7 14-8"/></Icon>,
  Shield: (p) => <Icon {...p}><path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5L16 9"/></Icon>,
  Zap: (p) => <Icon {...p}><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></Icon>,
  // Other
  Phone: (p) => <Icon {...p}><path d="M5 4a1 1 0 0 1 1-1h3l2 5-2.5 1.5a11 11 0 0 0 5 5L15 12l5 2v3a1 1 0 0 1-1 1A16 16 0 0 1 4 6c0-1 1-2 1-2z"/></Icon>,
  Message: (p) => <Icon {...p}><path d="M21 12a8 8 0 0 1-8 8c-1.5 0-3-.4-4.2-1L3 20l1-5.5C3.4 13 3 11.5 3 10a8 8 0 1 1 18 2z"/></Icon>,
  Send: (p) => <Icon {...p}><path d="M22 2L11 13M22 2l-7 20-4-9-9-4z"/></Icon>,
  Clock: (p) => <Icon {...p}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></Icon>,
  Tag: (p) => <Icon {...p}><path d="M20.6 13.4L13.4 20.6a2 2 0 0 1-2.8 0l-7.8-7.8a2 2 0 0 1-.6-1.4V4a2 2 0 0 1 2-2h7.4a2 2 0 0 1 1.4.6l7.8 7.8a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.2"/></Icon>,
  Note: (p) => <Icon {...p}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M9 13h6M9 17h4"/></Icon>,
  Gift: (p) => <Icon {...p}><rect x="3" y="8" width="18" height="4"/><path d="M12 8v13M5 12v9h14v-9"/><path d="M12 8c-3 0-3-5 0-5s3 5 0 5zM12 8c3 0 3-5 0-5"/></Icon>,
  Globe: (p) => <Icon {...p}><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a13 13 0 0 1 0 18M12 3a13 13 0 0 0 0 18"/></Icon>,
  LogOut: (p) => <Icon {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></Icon>,
  Wallet: (p) => <Icon {...p}><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 14h2"/></Icon>,
  Star: (p) => <Icon {...p}><path d="M12 3l2.7 5.5 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.8 1-6.1L3.2 9.4l6.1-.9z" fill="currentColor" stroke="none"/></Icon>,
  StarO: (p) => <Icon {...p}><path d="M12 3l2.7 5.5 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.8 1-6.1L3.2 9.4l6.1-.9z"/></Icon>,
  Sun: (p) => <Icon {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></Icon>,
  Moon: (p) => <Icon {...p}><path d="M21 13a9 9 0 1 1-10-10 7 7 0 0 0 10 10z"/></Icon>,
  Refresh: (p) => <Icon {...p}><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5"/></Icon>,
  // Logo glyph (water-drop + leaf in our own original shape)
  Logo: ({ size = 32, ...rest }) => (
    <svg width={size} height={size * 1.05} viewBox="0 0 48 50" {...rest}>
      <path d="M24 2 C32 12, 42 22, 42 32 a18 18 0 0 1-36 0 C6 22, 16 12, 24 2z"
        fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round"/>
      <path d="M24 6 L24 44" stroke="currentColor" strokeWidth="1.5"/>
      <path d="M24 16 L13 24 L24 18z" fill="#84C42B"/>
      <path d="M24 28 L34 32 L24 30z" fill="#F2E81C"/>
    </svg>
  ),
};

window.Icons = Icons;
