import os,json
from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
p=PostgresDatabase(os.environ['THESISTRACE_DATABASE_URL']);p.open()
try:
 with p.transaction() as t:
  t.execute('SET TRANSACTION READ ONLY')
  print(json.dumps({'schema':t.execute('SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton=true').fetchone(),'expected':_fingerprint(CORE_SCHEMA_DEFINITIONS),'research_counts':t.execute('SELECT status,count(*) AS count FROM research_runs.runs GROUP BY status').fetchall()}))
finally:p.close()
