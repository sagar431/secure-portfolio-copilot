import type { Capability } from '../types/auth'

export function hasCapability(
  grants: { capabilities: Capability[] }[],
  capability: Capability,
) {
  return grants.some((grant) => grant.capabilities.includes(capability))
}
