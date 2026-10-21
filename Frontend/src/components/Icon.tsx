import { P } from '../icons'
import type { IconName } from '../icons'

export default function Icon({ n }: { n: IconName }) {
  return <svg className="ic" viewBox="0 0 24 24"><path d={P[n]} /></svg>
}
