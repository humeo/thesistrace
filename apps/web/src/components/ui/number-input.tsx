import { NumberField } from "@base-ui/react/number-field";
import { Minus, Plus } from "@phosphor-icons/react";
import { cn } from "cn";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput, InputGroupText } from "./input-group";

type NumberInputProps = Pick<NumberField.Root.Props, "id" | "value" | "onValueChange" | "min" | "max" | "step" | "smallStep" | "largeStep" | "disabled"> & {
  className?: string;
  placeholder?: string;
  suffix?: string;
  incrementLabel: string;
  decrementLabel: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
};

export function NumberInput({ className, placeholder, suffix, incrementLabel, decrementLabel,
  "aria-invalid": invalid, "aria-describedby": describedBy, ...props }: NumberInputProps) {
  return <NumberField.Root {...props} allowOutOfRange format={{ useGrouping: false, maximumFractionDigits: 20 }}
    className={cn("min-w-0", className)}>
    <NumberField.Group render={<InputGroup />}>
      <NumberField.Input render={<InputGroupInput />} placeholder={placeholder}
        aria-invalid={invalid} aria-describedby={describedBy} />
      <InputGroupAddon>
        <NumberField.Decrement aria-label={decrementLabel} render={<InputGroupButton size="icon-sm" />}>
          <Minus aria-hidden="true" />
        </NumberField.Decrement>
      </InputGroupAddon>
      <InputGroupAddon align="inline-end">
        {suffix && <InputGroupText>{suffix}</InputGroupText>}
        <NumberField.Increment aria-label={incrementLabel} render={<InputGroupButton size="icon-sm" />}>
          <Plus aria-hidden="true" />
        </NumberField.Increment>
      </InputGroupAddon>
    </NumberField.Group>
  </NumberField.Root>;
}
