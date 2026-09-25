import { cn } from "cn"
import { SpinnerIcon } from "@phosphor-icons/react"

function Spinner({ className, ...props }: React.ComponentProps<"svg">) {
  return (
    <SpinnerIcon data-slot="spinner" aria-hidden="true" className={cn("size-4 motion-safe:animate-spin", className)} {...props} />
  )
}

export { Spinner }
