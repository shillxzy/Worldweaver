import { booksApi } from '../api/books'

/* ---------- власні обкладинки ---------- */
type CoverBook = { id: number; title: string; accent: string; has_cover?: boolean; updated_at?: string }

/** The uploaded cover image, or one of two generated styles (deep sea / concentric rings). */
export default function CoverArt({ p, big }: { p: CoverBook; big?: boolean }) {
  if (p.has_cover && p.updated_at) {
    return <img className="cover-img" src={booksApi.coverUrl({ id: p.id, updated_at: p.updated_at })} alt={p.title} draggable={false} />
  }
  const a = p.accent
  const sea = p.id % 2 === 1
  const gid = `cv${p.id}${big ? 'b' : ''}`
  return (
    <svg viewBox="0 0 300 400" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={'g' + gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={sea ? '#0f3a52' : '#2a1342'} />
          <stop offset="1" stopColor={sea ? '#050e1a' : '#0e0716'} />
        </linearGradient>
        <radialGradient id={'r' + gid}>
          <stop offset="0" stopColor={a} stopOpacity="0.95" />
          <stop offset="1" stopColor={a} stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="300" height="400" fill={`url(#g${gid})`} />
      {sea ? (
        <g fill="none" stroke={a} strokeOpacity="0.5">
          <circle cx="150" cy="250" r="110" fill={`url(#r${gid})`} stroke="none" />
          <circle cx="150" cy="250" r="14" fill="#fff" stroke="none" />
          {[130, 160, 190, 220].map((y, i) => (
            <path key={y} strokeOpacity={0.55 - i * 0.1} d={`M0 ${y} Q 40 ${y - 18} 75 ${y} T 150 ${y} T 225 ${y} T 300 ${y}`} />
          ))}
        </g>
      ) : (
        <g fill="none" stroke={a}>
          <circle cx="150" cy="190" r="120" fill={`url(#r${gid})`} stroke="none" opacity="0.5" />
          {[30, 60, 90, 120].map((r, i) => (
            <circle key={r} cx="150" cy="190" r={r} strokeOpacity={0.9 - i * 0.18} strokeDasharray={`${40 + i * 30} ${14 + i * 6}`} />
          ))}
          <path d="M150 50v280" strokeOpacity="0.35" />
          <circle cx="150" cy="190" r="6" fill={a} stroke="none" />
        </g>
      )}
      {big && (
        <text x="150" y="352" textAnchor="middle" fontFamily="Fraunces, Georgia, serif" fontWeight="700" fontSize="25" fill="#fff">
          {p.title.length > 22 ? p.title.slice(0, 21) + '…' : p.title}
        </text>
      )}
    </svg>
  )
}
