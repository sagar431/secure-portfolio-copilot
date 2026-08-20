export type Capability =
  'QUERY_DOCUMENTS' | 'MANAGE_UPLOADS' | 'ADMINISTER_PLATFORM'

export interface IdentityData {
  id: string
  email: string
  display_name: string
}

export interface TenantData {
  id: string
  slug: string
  name: string
}

export interface MembershipData {
  id: string
  tenant: TenantData
  role: string
  primary_department: string
}

export interface ScopeGrantData {
  workspace: TenantData
  company_ids: string[]
  company_slugs: string[]
  query_departments: string[]
  capabilities: Capability[]
}

export interface MeData {
  identity: IdentityData
  active_memberships: MembershipData[]
  authorization_scope: {
    grants: ScopeGrantData[]
  }
}

export interface TokenData {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}
