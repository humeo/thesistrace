import { Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { Skeleton } from '../components/ui/skeleton';
import { useTranslation } from '../i18n';

/** Load near the viewport, then retain the preview's state while scrolling or translating. */
export function DeferredPreview({ children, height }: { children: ReactNode; height: number }) {
  const { t } = useTranslation('common');
  const host = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '240px' });
    observer.observe(host.current!);
    return () => observer.disconnect();
  }, []);
  const placeholder = <Skeleton role="status" aria-label={t('loadingWorkspace')} style={{ height }} />;
  return <div ref={host}><Suspense fallback={placeholder}>{visible ? children : placeholder}</Suspense></div>;
}
