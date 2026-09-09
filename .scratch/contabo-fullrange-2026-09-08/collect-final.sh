set -eu
for worker in thesistrace-research-worker-1 thesistrace-research-worker-2 thesistrace-research-worker-3 thesistrace-batch-research-worker-1 thesistrace-batch-research-worker-2; do
  ssh -o BatchMode=yes thesistrace-contabo "docker logs --since 2026-09-08T14:02:00Z $worker 2>&1" > ".scratch/contabo-fullrange-2026-09-08/$worker.log"
done
ssh -o BatchMode=yes thesistrace-contabo 'docker ps --format "{{.Names}} {{.Status}}"; for worker in thesistrace-research-worker-1 thesistrace-research-worker-2 thesistrace-research-worker-3 thesistrace-batch-research-worker-1 thesistrace-batch-research-worker-2; do docker inspect --format "{{.Name}} image={{.Image}} cpu={{.HostConfig.NanoCpus}} memory={{.HostConfig.Memory}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}" "$worker"; docker exec "$worker" cat /sys/fs/cgroup/memory.events; done' > .scratch/contabo-fullrange-2026-09-08/final-health.txt
