// Inline SVG icon set (replaces the emoji glyphs, which render very differently across OS/browsers).
// Stroke icons use currentColor so they follow the button's text color automatically; sun/dusk/moon and
// the compass needle are small filled shapes since celestial glyphs read better solid than outlined.
const STROKE = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
const svg = (body) => `<svg viewBox="0 0 24 24" width="1em" height="1em" aria-hidden="true" ${STROKE}>${body}</svg>`;

export const ICONS = {
  sun: svg('<circle cx="12" cy="12" r="4.2" fill="currentColor" stroke="none"/><path d="M12 2.2v3M12 18.8v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2.2 12h3M18.8 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'),
  sunset: svg('<path d="M3 18.5h18"/><path d="M6 18.5A6 6 0 0 1 18 18.5Z" fill="currentColor" stroke="none"/><path d="M12 6.3v3M6.9 9.7l2 2M17.1 9.7l-2 2"/>'),
  moon: svg('<path d="M20 14.6A8.6 8.6 0 1 1 9.4 4a7.2 7.2 0 0 0 10.6 10.6z" fill="currentColor" stroke="none"/>'),
  pin: svg('<path d="M12 21s7-6.3 7-11.6A7 7 0 0 0 5 9.4C5 14.7 12 21 12 21z"/><circle cx="12" cy="9.4" r="2.3"/>'),
  camera: svg('<path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2l1-1.6A1.5 1.5 0 0 1 9.8 4.6h4.4a1.5 1.5 0 0 1 1.3.8L16.5 7h2A1.5 1.5 0 0 1 20 8.5v9A1.5 1.5 0 0 1 18.5 19h-13A1.5 1.5 0 0 1 4 17.5v-9z"/><circle cx="12" cy="12.5" r="3.4"/>'),
  gear: svg('<path d="M4 6h8M18 6h2M4 12h2M12 12h8M4 18h9M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="15" cy="18" r="2"/>'),
  help: svg('<circle cx="12" cy="12" r="9"/><path d="M9.2 9.4a2.9 2.9 0 1 1 4.5 2.4c-.9.6-1.7 1.2-1.7 2.5"/><circle cx="12" cy="17.3" r="0.65" fill="currentColor" stroke="none"/>'),
  train: svg('<rect x="5" y="4" width="14" height="12" rx="3"/><path d="M5 12h14M9 16l-2 3M15 16l2 3"/><circle cx="9" cy="8.5" r="0.9" fill="currentColor" stroke="none"/><circle cx="15" cy="8.5" r="0.9" fill="currentColor" stroke="none"/>'),
  bell: svg('<path d="M12 3.2a5 5 0 0 0-5 5v3.4c0 1-.4 2-1.2 2.7l-.8.7h14l-.8-.7c-.8-.7-1.2-1.7-1.2-2.7V8.2a5 5 0 0 0-5-5z"/><path d="M9.4 18a2.6 2.6 0 0 0 5.2 0"/>'),
  footprints: svg('<ellipse cx="9" cy="8" rx="2.1" ry="3"/><ellipse cx="15" cy="15.2" rx="2.1" ry="3"/><circle cx="9" cy="4" r="0.9" fill="currentColor" stroke="none"/><circle cx="15" cy="11.2" r="0.9" fill="currentColor" stroke="none"/>'),
  hand: svg('<path d="M8 21v-8.5a1.5 1.5 0 0 1 3 0V15M11 21v-9.5a1.5 1.5 0 0 1 3 0V15M14 21v-8a1.5 1.5 0 0 1 3 0v5.5M8 15.5 6.3 13a1.4 1.4 0 0 1 2-2l1.7 1.7"/>'),
  compass: svg('<circle cx="12" cy="12" r="9"/><path d="M15 9l-2 5-4 1.5 2-5.5z" fill="currentColor" stroke="none"/>'),
};

/** the time-of-day icon for the toolbar clock button */
export const timeIcon = (name) => ICONS[{ day: 'sun', dusk: 'sunset', night: 'moon' }[name] || 'sunset'];
