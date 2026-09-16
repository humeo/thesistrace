import json,os
from thesistrace._postgres import PostgresDatabase
from thesistrace._postgres.schema import _fingerprint
from thesistrace.entrypoints.schema import CORE_SCHEMA_DEFINITIONS
print(json.dumps({'image_expected_fingerprint':_fingerprint(CORE_SCHEMA_DEFINITIONS)}))
db=PostgresDatabase(os.environ['THESISTRACE_DATABASE_URL']);db.open()
try:
 with db.transaction() as t:
  t.execute('SET TRANSACTION READ ONLY')
  print(json.dumps(t.execute('SELECT fingerprint FROM thesistrace_meta.schema_contract WHERE singleton = true').fetchone()))
finally:db.close()
