import { NumberInput } from "../components/ui/number-input";
import { useTranslation } from "../i18n";

export function ResearchNumberInput({ id, label, value, onChange, percentage = false, min = 0, max,
  placeholder, error }: {
  id: string; label: string; value: string; onChange: (value: string) => void;
  percentage?: boolean; min?: number; max?: number; placeholder?: string; error?: string;
}) {
  const { t } = useTranslation("research");
  return <NumberInput id={id} className="max-w-40" value={value === "" ? null : Number(value)}
    onValueChange={number => onChange(number === null ? "" : String(number))}
    min={min} max={max} step={percentage ? "any" : 1} smallStep={percentage ? 0.1 : 1}
    suffix={percentage ? "%" : undefined} placeholder={placeholder}
    decrementLabel={t("decrease", { label })} incrementLabel={t("increase", { label })}
    aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} />;
}
