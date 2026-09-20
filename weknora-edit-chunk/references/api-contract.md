# Weknora Chunk API Contract

## Authentication

Set `WEKNORA_BASE_URL` to either the Weknora origin (for example, `http://host:8781`) or the API root copied from an integration page (for example, `http://host:8781/api/v1`). The bundled script normalizes both forms and never produces `/api/v1/api/v1`.

Supply exactly one of:

- `WEKNORA_API_KEY`: sent as `X-API-Key`. Chunk reads require `retrieve`; chunk updates require `ingest`. A KB-restricted key must include the target KB. Full-access keys also work but are not recommended.
- `WEKNORA_ACCESS_TOKEN`: sent as `Authorization: Bearer <token>`. Reads require Viewer+ and KB read access. Updates require KB creator or Admin+ and KB write access.

The update endpoint is protected. An unauthenticated request returns 401.

## Endpoints

| Action | Method and path | Notes |
| --- | --- | --- |
| List chunks | `GET /api/v1/chunks/:knowledge_id` | Supports `page`, `page_size`, optionally `chunk_type`. |
| Fetch one chunk | `GET /api/v1/chunks/by-id/:chunk_id` | Use before a write to obtain current content and revision. |
| Update one chunk | `PUT /api/v1/chunks/:knowledge_id/:chunk_id` | Replaces whole `content` for the chosen chunk. |
| Check revisions | `GET /api/v1/chunks/:knowledge_id/:chunk_id/revisions` | Optional audit/history route. |
| Revert chunk | `POST /api/v1/chunks/:knowledge_id/:chunk_id/revert` | Not invoked by this skill without a separately explicit user request. |

`PUT` body:

```json
{
  "content": "The complete new chunk content",
  "expected_revision": 7
}
```

`expected_revision` must match the current `content_revision`. A mismatch returns 409. A successful content update increments the revision and asynchronously updates retrieval indexing. Inspect `index_status`: normally `processing`, then `ready`; `failed` indicates a retry or operational investigation is required.

## Document Discovery

- `GET /api/v1/knowledge-bases` lists available KBs.
- `GET /api/v1/knowledge-bases/:knowledge_base_id/knowledge` lists documents under one KB.
- `preview-replace`, `commit-replace`, and `verify-replace` internally search every API-visible KB by exact document name and obtain all required IDs. Do not construct IDs from a chat citation, title, or example.
- Use exact name comparisons only for a write workflow. Duplicate names require user clarification.

## Official Capability Boundary

The HTTP API supports updating an existing chunk. The upstream MCP server currently exposes chunk listing and deletion but no `update_chunk` tool. Its `update_knowledge_from_text` tool targets an entire manual Markdown knowledge entry and is not an equivalent chunk-edit operation.
