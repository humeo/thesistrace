export const publicPolicyPaths = ["/terms", "/privacy", "/refunds", "/pricing"] as const;
export type PublicPolicyPath = typeof publicPolicyPaths[number];
export function isPublicPolicyPath(path: string): path is PublicPolicyPath {
  return publicPolicyPaths.some(candidate => candidate === path);
}
