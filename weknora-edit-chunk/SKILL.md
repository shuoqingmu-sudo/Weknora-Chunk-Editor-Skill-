---
name: weknora-edit-chunk
description: Safely locate, preview, update, and verify one existing text chunk in a Weknora knowledge-base document through its authenticated API. Use when asked to replace or revise exact text in a specific Weknora document chunk, inspect chunk content or revisions before such an edit, or diagnose Weknora chunk-update authentication, permission, or version conflicts. Do not use for new-file upload, whole-document replacement, or chunk deletion.
---

# Weknora Chunk Editor

Edit an existing Weknora chunk with the supplied script. Read `references/api-contract.md` before configuring credentials or interpreting an API failure.

## Configure

Set `WEKNORA_BASE_URL` and exactly one credential. `WEKNORA_BASE_URL` may be either the server origin or the API URL ending in `/api/v1`; the script normalizes both forms. Prefer a dedicated API key limited to the target knowledge base with `retrieve` and `ingest` permissions. Never print, persist, or retrieve browser-stored credentials.

```powershell
$env:WEKNORA_BASE_URL = 'http://host:8781'
# This equivalent form is also valid:
# $env:WEKNORA_BASE_URL = 'http://host:8781/api/v1'
$env:WEKNORA_API_KEY = 'sk-...'
```

Use `WEKNORA_ACCESS_TOKEN` only when a JWT is deliberately supplied instead. Run the script with the available Python runtime:

```powershell
python scripts/weknora_chunk.py --help
```

## Workflow

1. Run `preview-replace --document-name <exact-document-name> --old-text <exact-old-text> --new-text <replacement>`. This command internally resolves every required ID through the configured API key. Never call `find-text`, `list-documents`, `get-chunk`, or `update-chunk` in the conversational edit flow.
2. Require the preview to return exactly one document and exactly one chunk. If it cannot, report the candidates or API-key scope issue. Never invent, abbreviate, or reuse internal chat IDs such as `b1` or `d2`.
3. Show the returned chunk index, exact before/after content, and `content_revision`. Obtain an explicit confirmation before a write unless the user has explicitly requested an unambiguous immediate commit.
4. Run `commit-replace` with exactly the same document name, old text, new text, and the `content_revision` from the preview. The script re-resolves the document and chunk before submitting the PUT; a changed revision is rejected.
5. Run `verify-replace` using document name and new text. Report the returned revision and `index_status`; `processing` means retrieval may lag until reindexing completes.

## Commands

```powershell
# Read-only preview; do this before every edit.
python scripts/weknora_chunk.py preview-replace --document-name '目标文档.md' --old-text '旧文本' --new-text '新文本'

# Mutation: use only the revision returned by the preview above.
python scripts/weknora_chunk.py commit-replace --document-name '目标文档.md' --old-text '旧文本' --new-text '新文本' --expected-revision <revision>

# Post-write validation.
python scripts/weknora_chunk.py verify-replace --document-name '目标文档.md' --new-text '新文本'
```

## Failure Rules

- On `401`, stop and request a valid credential; do not fall back to an unrelated credential.
- On `403`, stop. Verify the key has `ingest`, its KB allow-list includes the target KB, or the JWT user is the KB creator/Admin+ with write access.
- On `404`, report that the configured API key cannot access the named document or its knowledge base. Do not retry with an ID from a chat citation or attachment.
- On `409`, re-fetch the chunk, regenerate the diff, and obtain a fresh confirmation. Never overwrite a concurrent update.
- Do not use `update_knowledge_from_text`, file upload, or document reparse as a substitute for updating one existing chunk.

## Weknora Conversation Integration

This Codex skill calls the official HTTP API. It does not by itself appear as a tool in Weknora's own chat UI. To enable the same operation there, add an `update_chunk` tool to a custom MCP service or an approved fork of the official Weknora MCP server. The MCP tool must apply this same locate-preview-update-verify workflow and use a least-privilege service key.
