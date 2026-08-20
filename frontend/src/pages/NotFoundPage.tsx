import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <section className="hero">
      <p className="eyebrow">404</p>
      <h1>Page not found</h1>
      <Link to="/">Return to the application home</Link>
    </section>
  )
}
