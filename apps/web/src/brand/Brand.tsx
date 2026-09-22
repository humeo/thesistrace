export const PRODUCT_NAME = "Quantgrove";

type BrandMarkProps = Readonly<{
  size?: number;
  className?: string;
  inverse?: boolean;
}>;

/** Decorative mark; the enclosing link or wordmark supplies the accessible name. */
export function BrandMark({ size = 30, className, inverse = false }: BrandMarkProps) {
  return <img
    className={className}
    src={`/brand/quantgrove-mark${inverse ? "-inverse" : ""}.svg`}
    alt=""
    width={size}
    height={size}
  />;
}

/** A fragment preserves each surface's existing layout and sidebar collapse behavior. */
export function Brand({ wordmarkClassName = "", ...mark }: BrandMarkProps & Readonly<{ wordmarkClassName?: string }>) {
  return <>
    <BrandMark {...mark} />
    <span className={`quantgrove-wordmark ${wordmarkClassName}`.trim()}>{PRODUCT_NAME}</span>
  </>;
}
