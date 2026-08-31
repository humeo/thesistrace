# Authenticate remote Research Agent access with OAuth

Each remote MCP deployment is one OAuth-protected resource for one controlled ThesisTrace installation and accepts only request-context access tokens whose subject is an authorized Researcher. The visible Tool inventory is the intersection of the deployment allowlist and six Research or Tracking scopes; credentials never travel in Tool inputs, and remote access adds no Workspace, quota, billing, or Data Operator authority.
