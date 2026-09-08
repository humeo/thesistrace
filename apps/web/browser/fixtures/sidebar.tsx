import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import { AppShell } from '../../src/shell/AppShell';
import type { SessionHistoryController } from '../../src/chat/useSessionHistory';
const history: SessionHistoryController = { sessions: [], status: 'ready', error: null, nextCursor: null, loadingMore: false, refreshVersion: 0, refresh() {}, watchGeneratedTitle() {}, async loadMore() {}, async deleteSession() {}, async renameSession(session, title) { return { ...session, title }; } };
function Fixture() {
 const [path, navigate] = useState('/daily-tracks');
 return <AppShell currentPath={path} currentSessionId={null} isNewChat={false} isOperator={false} navigate={navigate} sessionHistory={history}><h1>{path}</h1></AppShell>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
