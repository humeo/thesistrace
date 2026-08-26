# Authenticate remote Research Agent access with OAuth

Each remote MCP deployment is an OAuth 2.1 protected resource serving one
controlled ThesisTrace installation. It accepts only request-context access
tokens whose subject is allowed for that installation, never tool-supplied
credentials, and does not add User, Workspace, Tenancy, or Data Operator
authority to Core; local stdio remains a development adapter rather than an
authentication alternative for remote access.
