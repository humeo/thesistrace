import json,os,time,subprocess,datetime
from pathlib import Path

def cpu():return list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:]))
prev=cpu()
print(json.dumps({'monitor_pid':os.getpid()}),flush=True)
for _ in range(360):
    t=time.monotonic();cur=cpu();delta=[a-b for a,b in zip(cur,prev)];prev=cur;total=sum(delta[:8]);
    stats=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}'],capture_output=True,text=True,timeout=15)
    containers=[json.loads(l) for l in stats.stdout.splitlines() if l]
    probe=subprocess.run(['curl','--silent','--output','/dev/null','--max-time','5','--resolve','thesistrace.com:443:127.0.0.1','--write-out','%{http_code} %{time_total}','https://thesistrace.com/.well-known/oauth-protected-resource/mcp'],capture_output=True,text=True,timeout=7)
    mem={l.split(':')[0]:int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith(('MemAvailable:','MemTotal:','SwapFree:'))}
    print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cpu_busy_pct':100*(total-delta[3]-delta[4])/total if total else 0,'iowait_pct':100*delta[4]/total if total else 0,'steal_pct':100*delta[7]/total if total else 0,'load':os.getloadavg(),'memory_kb':mem,'containers':containers,'api_probe':probe.stdout,'api_probe_exit':probe.returncode}),flush=True)
    time.sleep(max(0,10-(time.monotonic()-t)))
