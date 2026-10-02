import { Slider as SliderPrimitive } from "@base-ui/react/slider"
import { cn } from "cn"

function Slider<Value extends number | readonly number[]>({
  className,
  defaultValue,
  value,
  min = 0,
  max = 100,
  marks = [],
  orientation = "horizontal",
  thumbProps,
  ...props
}: SliderPrimitive.Root.Props<Value> & {
  marks?: readonly number[]
  thumbProps?: SliderPrimitive.Thumb.Props
}) {
  const values = value ?? defaultValue ?? [min, max]
  const _values = Array.isArray(values) ? values : [values]

  return (
    <SliderPrimitive.Root
      className={cn("data-horizontal:w-full data-vertical:h-full", className)}
      data-slot="slider"
      defaultValue={defaultValue}
      value={value}
      min={min}
      max={max}
      orientation={orientation}
      thumbAlignment="edge"
      {...props}
    >
      <SliderPrimitive.Control className="relative flex h-9 w-full touch-none items-center select-none data-disabled:opacity-50 data-vertical:h-full data-vertical:min-h-40 data-vertical:w-9 data-vertical:flex-col">
        <SliderPrimitive.Track
          data-slot="slider-track"
          className="relative grow overflow-hidden rounded-full bg-muted select-none data-horizontal:h-8 data-horizontal:w-full data-vertical:h-full data-vertical:w-8"
        >
          <SliderPrimitive.Indicator
            data-slot="slider-range"
            className="bg-primary select-none data-horizontal:h-full data-vertical:w-full"
          />
        </SliderPrimitive.Track>
        {marks.length > 0 && (
          <div aria-hidden="true" data-orientation={orientation} className="pointer-events-none absolute inset-x-4.5 inset-y-0 data-[orientation=vertical]:inset-x-0 data-[orientation=vertical]:inset-y-4.5">
            {marks.map((mark) => (
              <span key={mark}
                className="absolute size-1.5 rounded-full bg-foreground/40"
                style={orientation === "horizontal"
                  ? { left: `${((mark - min) / (max - min)) * 100}%`, top: "50%", transform: "translate(-50%, -50%)" }
                  : { bottom: `${((mark - min) / (max - min)) * 100}%`, left: "50%", transform: "translate(-50%, 50%)" }}
              />
            ))}
          </div>
        )}
        {Array.from({ length: _values.length }, (_, index) => (
          <SliderPrimitive.Thumb
            data-slot="slider-thumb"
            key={index}
            {...thumbProps}
            className={cn("relative block size-9 shrink-0 rounded-full border border-border bg-white ring-ring/50 transition-[color,box-shadow] select-none after:absolute after:-inset-2 hover:ring-2 has-[:focus-visible]:ring-2 focus-visible:outline-hidden active:ring-2 disabled:pointer-events-none disabled:opacity-50", thumbProps?.className)}
          />
        ))}
      </SliderPrimitive.Control>
    </SliderPrimitive.Root>
  )
}

export { Slider }
