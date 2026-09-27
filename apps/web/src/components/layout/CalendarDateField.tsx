import { CalendarBlank } from "@phosphor-icons/react";
import { enUS, zhCN } from "date-fns/locale";
import { useState, type Ref } from "react";

import { Button } from "../ui/button";
import { Calendar } from "../ui/calendar";
import { Field, FieldDescription, FieldError, FieldLabel } from "../ui/field";
import { InputGroup, InputGroupAddon, InputGroupInput } from "../ui/input-group";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../ui/popover";
import { interfaceLocale } from "../../i18n";
import { calendarDateFromIso, isoFromCalendarDate } from "./calendarDate";

export function CalendarDateField({
  id,
  label,
  openLabel,
  value,
  minimum,
  maximum,
  error,
  errorId,
  onChange,
  disabled = false,
  inputRef,
  help,
  helpId,
  required = false,
}: {
  id: string;
  label: string;
  openLabel: string;
  value: string;
  minimum: string | null;
  maximum: string | null;
  error?: string;
  errorId: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  help?: string;
  helpId?: string;
  required?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState<Date | undefined>();
  const selected = calendarDateFromIso(value);
  const start = minimum === null ? undefined : calendarDateFromIso(minimum);
  const end = maximum === null ? undefined : calendarDateFromIso(maximum);

  return (
    <Field className="min-w-0 text-sm" data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <InputGroup className="min-w-0 max-[767px]:h-11">
        <InputGroupInput
          id={id}
          aria-label={label}
          aria-invalid={Boolean(error)}
          aria-describedby={[helpId, error ? errorId : undefined].filter(Boolean).join(" ") || undefined}
          autoComplete="off"
          disabled={disabled}
          required={required}
          ref={inputRef}
          inputMode="numeric"
          onChange={(event) => onChange(event.target.value)}
          placeholder="YYYY-MM-DD"
          value={value}
        />
        <InputGroupAddon align="inline-end">
          <Popover open={open} onOpenChange={(next) => {
            if (next) setMonth(selected ?? end ?? start);
            setOpen(next);
          }}>
            <PopoverTrigger render={<Button variant="ghost" size="icon-sm" className="max-[767px]:size-11" aria-label={openLabel} disabled={disabled} />}>
              <CalendarBlank aria-hidden="true" />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-0">
              <PopoverTitle className="sr-only">{openLabel}</PopoverTitle>
              <Calendar
                aria-label={label}
                className="p-1 max-[359px]:p-0 [--cell-size:--spacing(11)]"
                mode="single"
                locale={interfaceLocale() === "zh-CN" ? zhCN : enUS}
                selected={selected}
                month={month ?? selected ?? end ?? start}
                onMonthChange={setMonth}
                startMonth={start}
                endMonth={end}
                disabled={[
                  ...(start ? [{ before: start }] : []),
                  ...(end ? [{ after: end }] : []),
                ]}
                onSelect={(day) => {
                  if (day === undefined) return;
                  onChange(isoFromCalendarDate(day));
                  setOpen(false);
                }}
              />
            </PopoverContent>
          </Popover>
        </InputGroupAddon>
      </InputGroup>
      {help && <FieldDescription id={helpId}>{help}</FieldDescription>}
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </Field>
  );
}
