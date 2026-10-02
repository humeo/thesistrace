import type { ReactNode } from "react";
import { InputGroup } from "../components/ui/input-group";

/** Shared surface for Alpha and exposure CodeMirror inputs. */
export function ResearchCodeInput({ children, height = 180 }: {
  children: ReactNode; height?: number;
}) {
  return <InputGroup className="resize-y overflow-hidden focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30"
    style={{ height, minHeight: 180 }}>
    {children}
  </InputGroup>;
}
