const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function groupsFromReport(report, filter) {
  const cases = [];
  function visit(suite, parents = []) {
    const titles = [...parents, suite.title].filter(Boolean);
    for (const spec of suite.specs ?? []) {
      const title = [...titles, spec.title].join(' ');
      if (!filter || new RegExp(filter).test(title)) cases.push({
        title, id: spec.id, isolated: spec.tags.includes('isolated'),
      });
    }
    for (const child of suite.suites ?? []) visit(child, titles);
  }
  for (const suite of report.suites ?? []) visit(suite);
  const ordinary = cases.filter(item => !item.isolated);
  return [
    ...(ordinary.length ? [{ name: 'ordinary', ids: ordinary.map(item => item.id), grep: ordinary.map(item => escape(item.title)).join('|') }] : []),
    ...cases.filter(item => item.isolated).map(item => ({ name: item.title, ids: [item.id], grep: escape(item.title) })),
  ];
}
