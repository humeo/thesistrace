import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { SelectionEligibilityView } from "./SelectionEligibility";

it("labels the frozen selection date and each actual exclusion count", () => {
  const markup = renderToStaticMarkup(<SelectionEligibilityView selection={{
    signal_session: "2026-08-05",
    eligibility_exclusions: { zero_volatility: 2, insufficient_history: 1, unavailable_return: 3 },
  }} />);
  expect(markup).toContain("selection Close 2026-08-05");
  expect(markup).toContain("Zero volatility: 2");
  expect(markup).toContain("Insufficient history: 1");
  expect(markup).toContain("Unavailable return: 3");
});

it("shows that weighting excluded no candidates without inventing counts", () => {
  const markup = renderToStaticMarkup(<SelectionEligibilityView selection={{
    signal_session: "2026-08-05", eligibility_exclusions: {},
  }} />);
  expect(markup).toContain("No candidates excluded by weighting.");
  expect(markup).not.toContain("Zero volatility:");
});
