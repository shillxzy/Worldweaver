export default function Header({ title, sub }: { title: string; sub?: string }) {
  return <div><h1>{title}</h1>{sub && <p className="sub">{sub}</p>}</div>
}
