# Planning Center Services MCP — PAT connection flow

This server preserves the original Planning Center Services tools, but removes PAT fields from all MCP tool schemas. Each user connects through an **OAuth-style authorization code + PKCE** flow, using a hosted form to submit their own Planning Center **Application ID and Secret**. This is **not** official Planning Center OAuth: the service stores the user's PAT (encrypted) and issues its own access and refresh tokens.

## Deployment

1. Provision a persistent PostgreSQL database (Render Postgres or another managed provider). A free Render web instance does **not** provide persistent local storage. Ensure the database is reachable from the web service.
2. Generate an encryption key locally: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
3. Configure Render environment variables:
   - `PUBLIC_URL` — exact HTTPS public origin, e.g. `https://pco-services-mcp.onrender.com` (no `/mcp`).
   - `DATABASE_URL` — PostgreSQL connection string, including SSL settings required by your provider.
   - `TOKEN_ENCRYPTION_KEY` — generated Fernet key. **Never change this without a data migration**: existing saved PATs become unreadable.
   - `PORT` — optional; Render usually supplies it.
4. Deploy with `python server.py`. Database tables are created automatically on startup.
5. Add `https://YOUR-HOST.onrender.com/mcp` as a custom remote MCP in a client supporting OAuth discovery, dynamic client registration and PKCE. The client should open the hosted PAT form.

## Security properties

- `/mcp` requires a valid Bearer token; unauthenticated requests return 401 and a protected-resource metadata pointer.
- Each OAuth client registers its callback URI. Authorization requires S256 PKCE, and authorization codes expire after 5 minutes and are single-use.
- Access tokens expire after 1 hour; refresh tokens after 30 days and are rotated on use.
- Only SHA-256 hashes of issued tokens are stored; PAT pairs are encrypted with Fernet at rest in PostgreSQL.
- Tool schemas never expose Application ID or Secret. Each request resolves the appropriate PAT from its authenticated session.
- `/revoke` supports token revocation. To disconnect completely, also revoke the original PAT in Planning Center.
- Do not expose `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, tokens or PATs in logs or commits.

## Routes

- `/.well-known/oauth-authorization-server` — authorization-server discovery
- `/.well-known/oauth-protected-resource` — resource discovery
- `/register` — dynamic OAuth client registration
- `/authorize` — consent/PAT form
- `/token` — authorization code or refresh token exchange
- `/revoke` — revoke a token
- `/mcp` — protected Streamable HTTP MCP endpoint
- `/health` — health check

## Important notes

- This is a self-hosted PAT broker. The operator is responsible for securely handling users' Planning Center credentials, database backups, abuse prevention and incident response.
- The hosted form verifies the PAT with a read call to the Services API. A PAT with no access to Services will be rejected.
- This implementation is a starting point for controlled deployment. Before broad public distribution, add registration/login rate limits, auditing without sensitive values, database lifecycle cleanup, and a security review.
- Compatibility with each specific MCP client must be verified in a deployed environment; it has not been end-to-end tested against a ferramenta de IA utilizada.
