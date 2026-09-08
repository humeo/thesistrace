import { AccountMenuContent } from '../../src/auth/AccountMenu';
export function AccountMenu() {
  return <AccountMenuContent session={{ displayLabel: 'Researcher', email: 'researcher@example.test', operator: false, researcherId: 'researcher_fixture' }} signOut={async () => ({ ok: true })}/>;
}
