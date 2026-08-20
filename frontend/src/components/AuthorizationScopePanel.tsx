import type { MeData } from '../types/auth'

function label(value: string) {
  return value.replaceAll('-', ' ').replaceAll('_', ' ')
}

export function AuthorizationScopePanel({ user }: { user: MeData }) {
  const membership = user.active_memberships[0]

  return (
    <section className="scope-panel" aria-labelledby="scope-title">
      <div>
        <p className="eyebrow">Authenticated identity</p>
        <h2 id="scope-title">{user.identity.display_name}</h2>
        <p>{user.identity.email}</p>
      </div>
      {membership ? (
        <dl className="identity-grid">
          <div>
            <dt>Tenant</dt>
            <dd>{membership.tenant.name}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{label(membership.role)}</dd>
          </div>
          <div>
            <dt>Department</dt>
            <dd>{label(membership.primary_department)}</dd>
          </div>
        </dl>
      ) : null}
      <div className="scope-list">
        {user.authorization_scope.grants.map((grant) => (
          <article
            key={`${grant.workspace.id}:${grant.capabilities.join(',')}`}
          >
            <h3>{grant.workspace.name}</h3>
            <p>
              <strong>Companies:</strong>{' '}
              {grant.company_slugs.length
                ? grant.company_slugs.join(', ')
                : 'No company access'}
            </p>
            <p>
              <strong>Query departments:</strong>{' '}
              {grant.query_departments.length
                ? grant.query_departments.map(label).join(', ')
                : 'None'}
            </p>
            <p>
              <strong>Capabilities:</strong>{' '}
              {grant.capabilities.map(label).join(', ')}
            </p>
          </article>
        ))}
      </div>
    </section>
  )
}
