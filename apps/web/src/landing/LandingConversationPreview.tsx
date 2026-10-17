import { Bubble } from '@ant-design/x';
import { BrandMark } from '../brand/Brand';
import { ChatUiProvider } from '../chat/ChatUiProvider';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { useTranslation } from '../i18n';
import { factorExamples } from './examples';

export default function LandingConversationPreview({ appearance, onSelectFactor }: { appearance: "light" | "dark"; onSelectFactor: (index: number) => void }) {
  const { t: translate } = useTranslation('landing');
  const t = translate('page', { returnObjects: true });
  return <ChatUiProvider appearance={appearance}>
    <Bubble.List autoScroll={false} items={[
      { key: 'question', role: 'user', placement: 'start', variant: 'filled', styles: { root: { paddingBlock: 0, paddingInlineStart: 36 } }, content: t.question },
      { key: 'answer', role: 'ai', variant: 'borderless', styles: { root: { paddingInlineEnd: 0 }, body: { width: '100%' }, content: { padding: 0 } }, avatar: <BrandMark tone="jade" size={20} inverse={appearance === "dark"} />, content: <>
        <p>{t.answer}</p>
        <Table className="qh-research-table"><TableHeader><TableRow><TableHead>{t.researchName}</TableHead><TableHead>{t.rankOne}</TableHead><TableHead>{t.rankFive}</TableHead></TableRow></TableHeader>
          <TableBody>{factorExamples.map((item, index) => <TableRow key={item.key}>
            <TableCell><Button variant="link" size="sm" onClick={() => onSelectFactor(index)}>{t[item.key]}</Button><code>{item.expression}</code></TableCell><TableCell>{item.oneDay}</TableCell><TableCell>{item.fiveDay}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </> },
    ]} />
  </ChatUiProvider>;
}
