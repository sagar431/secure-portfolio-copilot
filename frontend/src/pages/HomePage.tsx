import { BackendHealth } from '../components/BackendHealth'

export function HomePage() {
  return (
    <section className="hero" aria-labelledby="page-title">
      <p className="eyebrow">Development harness</p>
      <h1 id="page-title">
        A secure foundation, ready to grow one milestone at a time.
      </h1>
      <p className="hero-copy">
        This first slice proves the application shell, API contract, database
        readiness, and test harness. Product workflows begin in later approved
        milestones.
      </p>
      <BackendHealth />
    </section>
  )
}
