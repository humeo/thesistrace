import { Bubble, Sender } from '@ant-design/x';
import { CheckCircleIcon } from '@phosphor-icons/react';
import { BrandMark } from '../brand/Brand';
import { ChatUiProvider } from '../chat/ChatUiProvider';
import { Badge } from '../components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { useTranslation } from '../i18n';
import { factorExamples } from './examples';

export default function LandingConversationPreview() {
  const { t: translate } = useTranslation('landing');
  const t = translate('page', { returnObjects: true });
  return <ChatUiProvider>
    <Bubble.List autoScroll={false} items={[
      { key: 'question', role: 'user', placement: 'end', variant: 'filled', content: t.question },
      { key: 'answer', role: 'ai', variant: 'borderless', avatar: <BrandMark size={24} inverse />, content: <>
        <p>{t.answer}</p>
        <Table className="qh-research-table"><TableHeader><TableRow><TableHead>{t.researchName}</TableHead><TableHead>{t.rankOne}</TableHead><TableHead>{t.rankFive}</TableHead></TableRow></TableHeader>
          <TableBody>{factorExamples.map(item => <TableRow key={item.key}>
            <TableCell>{item.key === 'reversal' ? <a href="#evidence">{t[item.key]}</a> : <span className="qh-research-name">{t[item.key]}</span>}<Badge variant="outline"><CheckCircleIcon aria-hidden="true" />{t.completed}</Badge><code>{item.expression}</code></TableCell><TableCell>{item.oneDay}</TableCell><TableCell>{item.fiveDay}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </> },
    ]} />
    <Sender disabled placeholder={t.ask} aria-label={t.ask} footer={<span>{t.builtIn}</span>} />
  </ChatUiProvider>;
}
