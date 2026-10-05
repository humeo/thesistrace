import type { InterfaceLocale } from '../i18n';

/** Character composition adapted from Ant Design X's website SwitchBtn (MIT).
 * https://github.com/ant-design/x/blob/main/packages/x/.dumi/theme/slots/Header/SwitchBtn.tsx
 */
export function LanguageIcon({ language }: Readonly<{ language: InterfaceLocale }>) {
  return <span aria-hidden="true" className="qh-language-icon">
    <span data-active={language === 'zh-CN'}>中</span>
    <span data-active={language === 'en'}>En</span>
  </span>;
}
