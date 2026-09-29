import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import '../../src/styles.css';
import '../../src/research/research-perplexity.css';
import { AppShell } from '../../src/shell/AppShell';
import { Page, PageContent, PageHeader } from '../../src/components/layout/Page';
import type { SessionHistoryController } from '../../src/chat/useSessionHistory';
const history: SessionHistoryController = { sessions: [{ id: '00000000-0000-4000-8000-000000000001', title: 'Quality Alpha', created_at: '2026-08-29T04:00:00.000Z', activity_at: '2026-08-30T04:00:00.000Z', version: '2026-08-30T04:00:00.000Z', current_turn: null, latest_turn: null }], status: 'ready', error: null, nextCursor: null, loadingMore: false, refreshVersion: 0, refresh() {}, watchGeneratedTitle() {}, async loadMore() {}, async deleteSession() {}, async renameSession(session, title) { return { ...session, title }; } };
function Fixture() {
 const [path, navigate] = useState('/daily-tracks');
 return <AppShell currentPath={path} currentSessionId={null} isNewChat={false} isOperator={false} navigate={navigate} sessionHistory={history}>
  <Page><PageContent data-testid="workspace-content"><PageHeader title={path} />
   <div aria-label="Research content" style={{ height: 160, overflow: 'auto' }}><div style={{ height: 1000 }}>Research observations</div></div>
  </PageContent></Page>
 </AppShell>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
