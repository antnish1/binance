export default function TaddyBear() {
  return (
    <svg className="taddy-bear" viewBox="0 0 360 260" role="img" aria-label="Taddy bear mascot">
      <defs>
        <linearGradient id="fur" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#ffcf8e" />
          <stop offset="1" stopColor="#b56e3c" />
        </linearGradient>
        <linearGradient id="hoodie" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#263a62" />
          <stop offset="1" stopColor="#101827" />
        </linearGradient>
        <radialGradient id="glow">
          <stop offset="0" stopColor="#5f7cff" stopOpacity=".32" />
          <stop offset="1" stopColor="#5f7cff" stopOpacity="0" />
        </radialGradient>
        <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="12" stdDeviation="12" floodColor="#000814" floodOpacity=".45" />
        </filter>
      </defs>

      <ellipse cx="180" cy="220" rx="135" ry="28" fill="url(#glow)" />
      <g opacity=".7">
        <path d="M30 178 C82 132, 110 188, 152 140 S246 105, 330 128" fill="none" stroke="#5574ff" strokeWidth="3" />
        <circle cx="66" cy="157" r="4" fill="#67f0b2" />
        <circle cx="151" cy="141" r="4" fill="#67f0b2" />
        <circle cx="245" cy="105" r="4" fill="#67f0b2" />
        <circle cx="330" cy="128" r="4" fill="#67f0b2" />
      </g>

      <g filter="url(#shadow)">
        <circle cx="105" cy="72" r="36" fill="url(#fur)" />
        <circle cx="255" cy="72" r="36" fill="url(#fur)" />
        <circle cx="105" cy="72" r="18" fill="#8d4f2e" opacity=".52" />
        <circle cx="255" cy="72" r="18" fill="#8d4f2e" opacity=".52" />
        <ellipse cx="180" cy="112" rx="91" ry="83" fill="url(#fur)" />
        <ellipse cx="180" cy="130" rx="50" ry="37" fill="#f3c98e" />
        <circle cx="147" cy="101" r="10" fill="#10141d" />
        <circle cx="213" cy="101" r="10" fill="#10141d" />
        <circle cx="143" cy="97" r="3" fill="#fff" />
        <circle cx="209" cy="97" r="3" fill="#fff" />
        <ellipse cx="180" cy="120" rx="13" ry="10" fill="#2a1c19" />
        <path d="M180 129 C174 143, 158 143, 151 133 M180 129 C186 143, 202 143, 209 133" fill="none" stroke="#2a1c19" strokeWidth="4" strokeLinecap="round" />

        <path d="M109 164 C124 142, 148 139, 180 139 C212 139, 236 142, 251 164 L268 231 L92 231 Z" fill="url(#hoodie)" />
        <path d="M148 147 C156 163, 170 172, 180 172 C190 172, 204 163, 212 147" fill="none" stroke="#405b8f" strokeWidth="5" />
        <line x1="162" y1="158" x2="156" y2="197" stroke="#8298c2" strokeWidth="3" />
        <line x1="198" y1="158" x2="204" y2="197" stroke="#8298c2" strokeWidth="3" />
        <circle cx="156" cy="199" r="5" fill="#67f0b2" />
        <circle cx="204" cy="199" r="5" fill="#67f0b2" />

        <ellipse cx="98" cy="190" rx="27" ry="42" transform="rotate(15 98 190)" fill="url(#fur)" />
        <ellipse cx="262" cy="190" rx="27" ry="42" transform="rotate(-15 262 190)" fill="url(#fur)" />
        <rect x="118" y="188" width="124" height="75" rx="10" fill="#0a111c" stroke="#34476a" strokeWidth="3" />
        <path d="M162 223 h36 l-18 18 z" fill="#5f7cff" opacity=".7" />
        <circle cx="180" cy="220" r="8" fill="#6ef0b4" />
      </g>
    </svg>
  );
}
