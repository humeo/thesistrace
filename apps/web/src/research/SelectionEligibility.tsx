export type SelectionEligibility = {
  signal_session: string;
  eligibility_exclusions: Partial<Record<"zero_volatility" | "insufficient_history" | "unavailable_return", number>>;
};

const labels = {
  zero_volatility: "Zero volatility",
  insufficient_history: "Insufficient history",
  unavailable_return: "Unavailable return",
} as const;

export function SelectionEligibilityView({ selection }: { selection: SelectionEligibility }) {
  const counts = selection.eligibility_exclusions;
  return <div aria-label="Latest selection eligibility">
    <p>Weighting eligibility at selection Close {selection.signal_session}</p>
    {Object.keys(counts).length === 0
      ? <p>No candidates excluded by weighting.</p>
      : <ul>{(Object.keys(labels) as Array<keyof typeof labels>).filter(reason => counts[reason] !== undefined)
        .map(reason => <li key={reason}>{labels[reason]}: {counts[reason]}</li>)}</ul>}
  </div>;
}
