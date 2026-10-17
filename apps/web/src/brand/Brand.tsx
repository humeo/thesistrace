import { BrandWordmark } from "./BrandWordmark";

export const PRODUCT_NAME = "QAgentis";

type BrandMarkProps = Readonly<{
  size?: number;
  className?: string;
  inverse?: boolean;
  tone?: "jade";
}>;

/** Decorative mark; the enclosing link or wordmark supplies the accessible name. */
export function BrandMark({ size = 30, className, inverse = false, tone }: BrandMarkProps) {
  return <img
    className={className}
    src={`/brand/qhypo-mark${tone === "jade" ? "-jade" : ""}${inverse ? "-inverse" : ""}.svg`}
    alt=""
    width={size * 4 / 3}
    height={size}
  />;
}

/** A fragment preserves each surface's existing layout and sidebar collapse behavior. */
export function Brand({ wordmarkClassName = "", ...mark }: BrandMarkProps & Readonly<{ wordmarkClassName?: string }>) {
  return <>
    <BrandMark {...mark} />
    <span className={`quantgrove-wordmark ${wordmarkClassName}`.trim()}><BrandWordmark /><span className="sr-only">{PRODUCT_NAME}</span></span>
  </>;
}
