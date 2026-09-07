import { configurationFile, loadConfiguration, root } from '../config/configuration.mjs';
import { run } from '../process.mjs';

export function deployment(mode) {
  const env = loadConfiguration({ file: configurationFile(mode), mode });
  const project = mode === 'production' ? 'thesistrace' : 'thesistrace-dev';
  return (...command) => {
    const options = typeof command.at(-1) === 'object' ? command.pop() : {};
    return run('docker', ['compose', '--project-name', project, '--env-file', '/dev/null',
      '--file', `${root}/deploy/core/compose.yaml`, '--file', `${root}/deploy/core/compose.${mode === 'development' ? 'dev' : 'production'}.yaml`, ...command], { ...options, env });
  };
}
