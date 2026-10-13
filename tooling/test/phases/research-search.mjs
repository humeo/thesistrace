export async function researchSearch(run) {
  await run.phase('search-infrastructure', () => run.compose(['up', '--detach', '--wait', '--wait-timeout', '120', 'postgres']));
  await run.updatePorts('postgres');
  await run.phase('search-performance', () => run.host([
    'uv', 'run', '--no-sync', 'python', `${run.repo_root}/apps/core/tools/check_research_search.py`,
    '--output', `${run.evidence_dir}/research-search.json`,
  ]));
}
