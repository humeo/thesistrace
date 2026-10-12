import { OTPField as OTPFieldPrimitive } from "@base-ui/react/otp-field"
import { cn } from "cn"

import { Input } from "@/components/ui/input"

function InputOTP({ className, ...props }: OTPFieldPrimitive.Root.Props) {
  return (
    <OTPFieldPrimitive.Root
      data-slot="input-otp"
      className={cn("flex gap-2", className)}
      {...props}
    />
  )
}

function InputOTPSlot(props: OTPFieldPrimitive.Input.Props) {
  return (
    <OTPFieldPrimitive.Input
      data-slot="input-otp-slot"
      render={<Input className="size-10 shrink-0 px-0 text-center" />}
      {...props}
    />
  )
}

export { InputOTP, InputOTPSlot }
