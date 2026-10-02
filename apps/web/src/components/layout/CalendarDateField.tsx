import { CalendarBlank, CaretDown, CaretLeft, CaretRight } from "@phosphor-icons/react";
import { enUS, zhCN } from "date-fns/locale";
import { useRef, useState, type Ref } from "react";

import { Button } from "../ui/button";
import { Calendar } from "../ui/calendar";
import { Field, FieldDescription, FieldError, FieldLabel } from "../ui/field";
import { InputGroup, InputGroupAddon, InputGroupInput } from "../ui/input-group";
import { Popover, PopoverClose, PopoverContent, PopoverTitle, PopoverTrigger } from "../ui/popover";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { interfaceLocale } from "../../i18n";
import { calendarDateFromIso, isoFromCalendarDate } from "./calendarDate";

function boundedMonth(value: Date, start?: Date, end?: Date): Date {
  const month = new Date(value.getFullYear(), value.getMonth(), 1);
  const first = start && new Date(start.getFullYear(), start.getMonth(), 1);
  const last = end && new Date(end.getFullYear(), end.getMonth(), 1);
  if (first && month < first) return first;
  if (last && month > last) return last;
  return month;
}

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
  const [yearPickerOpen, setYearPickerOpen] = useState(false);
  const [yearPage, setYearPage] = useState(0);
  // Switching views unmounts the focused button, so focus the popup first.
  const popoverContentRef = useRef<HTMLDivElement>(null);
  const inputDate = calendarDateFromIso(value);
  const start = minimum === null ? undefined : calendarDateFromIso(minimum);
  const end = maximum === null ? undefined : calendarDateFromIso(maximum);
  const selected = inputDate && (!start || inputDate >= start) && (!end || inputDate <= end) ? inputDate : undefined;
  const displayMonth = boundedMonth(month ?? inputDate ?? end ?? start ?? new Date(), start, end);
  const showAllYears = start !== undefined && end !== undefined && end.getFullYear() - start.getFullYear() <= 23;
  const firstYear = showAllYears ? start.getFullYear() : yearPage;
  const lastYear = showAllYears ? end.getFullYear() : yearPage + 11;
  const isChinese = interfaceLocale() === "zh-CN";
  // Keep the existing open-ended year navigation; DayPicker's year dropdown adds implicit year bounds.
  const monthOptions = Array.from({ length: 12 }, (_, value) => {
    const date = new Date(displayMonth.getFullYear(), value, 1);
    return {
      value,
      label: date.toLocaleString(isChinese ? "zh-CN" : "en-US", { month: "long" }),
      disabled: date.getTime() !== boundedMonth(date, start, end).getTime(),
    };
  });
  const yearControl = <Button type="button" variant="ghost" size="sm" className="h-8 gap-1 px-1.5 text-sm font-medium"
    aria-label={isChinese ? "选择年份" : "Choose year"}
    onClick={() => {
      popoverContentRef.current?.focus();
      setYearPage(Math.floor(displayMonth.getFullYear() / 12) * 12);
      setYearPickerOpen(true);
    }}>
    {displayMonth.getFullYear()}{isChinese ? "年" : ""}<CaretDown aria-hidden="true" className="size-3" />
  </Button>;

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
          <Popover open={open} modal="trap-focus" onOpenChange={(next) => {
            if (next) {
              setMonth(boundedMonth(inputDate ?? end ?? start ?? new Date(), start, end));
              setYearPickerOpen(false);
            }
            setOpen(next);
          }}>
            <PopoverTrigger render={<Button variant="ghost" size="icon-sm" className="max-[767px]:size-11" aria-label={openLabel} disabled={disabled} />}>
              <CalendarBlank aria-hidden="true" />
            </PopoverTrigger>
            <PopoverContent ref={popoverContentRef} tabIndex={-1} align="end" className="w-[270px] p-0">
              <PopoverTitle className="sr-only">{openLabel}</PopoverTitle>
              <PopoverClose className="sr-only" aria-label={isChinese ? "关闭日历" : "Close calendar"} />
              {yearPickerOpen ? (
                <div className="p-2">
                  <div className="mb-2 flex h-8 items-center justify-between gap-1">
                    {showAllYears ? (
                      <Button type="button" variant="ghost" size="sm" className="h-8 gap-1 px-1.5"
                        onClick={() => { popoverContentRef.current?.focus(); setYearPickerOpen(false); }}>
                        <CaretLeft aria-hidden="true" />{isChinese ? "返回日历" : "Back to calendar"}
                      </Button>
                    ) : (
                      <Button type="button" variant="ghost" size="icon-sm"
                        aria-label={isChinese ? "更早的年份" : "Earlier years"}
                        disabled={start !== undefined && firstYear <= start.getFullYear()}
                        onClick={() => setYearPage((current) => current - 12)}>
                        <CaretLeft aria-hidden="true" />
                      </Button>
                    )}
                    <span className="text-xs tabular-nums text-muted-foreground">{firstYear}–{lastYear}</span>
                    {showAllYears ? <span className="size-8" aria-hidden="true" /> : (
                      <Button type="button" variant="ghost" size="icon-sm"
                        aria-label={isChinese ? "更晚的年份" : "Later years"}
                        disabled={end !== undefined && lastYear >= end.getFullYear()}
                        onClick={() => setYearPage((current) => current + 12)}>
                        <CaretRight aria-hidden="true" />
                      </Button>
                    )}
                  </div>
                  <div role="group" aria-label={isChinese ? "选择年份" : "Choose year"} className="grid grid-cols-4 gap-1">
                    {Array.from({ length: lastYear - firstYear + 1 }, (_, index) => firstYear + index).map((year) => (
                      <Button key={year} type="button" size="sm"
                        variant={year === displayMonth.getFullYear() ? "outline" : "ghost"}
                        className="h-8 px-1 tabular-nums" aria-pressed={year === displayMonth.getFullYear()}
                        disabled={(start !== undefined && year < start.getFullYear()) || (end !== undefined && year > end.getFullYear())}
                        onClick={() => {
                          popoverContentRef.current?.focus();
                          setMonth(boundedMonth(new Date(year, displayMonth.getMonth(), 1), start, end));
                          setYearPickerOpen(false);
                        }}>
                        {year}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : (
                <Calendar
                  aria-label={label}
                  className="p-1 max-[359px]:p-0 [--cell-size:--spacing(9)]"
                  mode="single"
                  locale={isChinese ? zhCN : enUS}
                  selected={selected}
                  month={displayMonth}
                  onMonthChange={setMonth}
                  startMonth={start}
                  endMonth={end}
                  components={{
                    CaptionLabel: () => <div className="flex items-center gap-0.5">
                      {isChinese && yearControl}
                      <Select value={displayMonth.getMonth()} items={monthOptions}
                        onValueChange={next => {
                          if (next === null) return;
                          popoverContentRef.current?.focus();
                          setMonth(new Date(displayMonth.getFullYear(), next, 1));
                        }}>
                        <SelectTrigger aria-label={isChinese ? "选择月份" : "Choose month"} size="sm"
                          className="h-8 border-0 bg-transparent px-1.5 shadow-none">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="max-h-72 min-w-32"><SelectGroup>
                          {monthOptions.map(option => <SelectItem key={option.value} value={option.value} disabled={option.disabled}>{option.label}</SelectItem>)}
                        </SelectGroup></SelectContent>
                      </Select>
                      {!isChinese && yearControl}
                    </div>,
                  }}
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
              )}
            </PopoverContent>
          </Popover>
        </InputGroupAddon>
      </InputGroup>
      {help && <FieldDescription id={helpId}>{help}</FieldDescription>}
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </Field>
  );
}
