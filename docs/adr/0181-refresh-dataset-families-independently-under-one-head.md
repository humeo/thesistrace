# Refresh Dataset Families independently under one Head

Superseded by [ADR-0254](0254-publish-data-refresh-as-one-retryable-generation.md).

Market, Financial, and Industry Refresh rebuild their own target families but publish a complete validated Data Generation behind one Dataset Head. A concurrent Head change requires recomposition and validation, retaining independent collection boundaries without allowing mutually inconsistent family heads.
