# Agent schema

`schema.sql` is the reviewed physical schema used by the Agent initializer. It
contains the pinned Mastra PostgreSQL memory and agentic-workflow tables plus
ThesisTrace's minimal Session-ownership and Run-audit tables. The Agent runtime
never creates or alters these objects.

`catalog-contract.json` is generated from this SQL in an isolated PostgreSQL
instance and compared byte-for-byte after canonical JSON normalization at
initializer and runtime startup. A populated non-matching schema fails closed;
there is no migration or compatibility path.
