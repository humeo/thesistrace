// Captured from the completed homepage walkthrough on 2026-10-04.
// Factor batch: batch_2b897c76f15c460c9268. Daily track: track_fee00eb22ee4406fa835.
// Returns retain the two-decimal percentage precision displayed by Daily review.
export const factorExamples = [
  { key: 'reversal' as const, expression: '-rank(pct_change(close, 5))', oneDay: '0.082', fiveDay: '0.043' },
  { key: 'momentum' as const, expression: 'rank(pct_change(close, 20))', oneDay: '-0.224', fiveDay: '-0.302' },
];
export const trackingExample = {
  returns: [
    ['2026-08-31', 0], ['2026-09-01', 0.0504], ['2026-09-02', 0.0292],
    ['2026-09-03', 0.0478], ['2026-09-04', 0.0463], ['2026-09-07', 0.0183],
    ['2026-09-08', 0.0276], ['2026-09-09', 0.0292], ['2026-09-10', 0.0024],
    ['2026-09-11', -0.0194], ['2026-09-14', -0.0368], ['2026-09-15', -0.0213],
    ['2026-09-16', -0.0332], ['2026-09-17', -0.0123],
  ].map(([session, net_return]) => ({ session: String(session), net_return: Number(net_return) })),
};
