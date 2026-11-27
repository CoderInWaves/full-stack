# Runtime Policy Management

YAML remains the startup configuration. HTTP administrators can activate a new full `PolicyConfig` snapshot without restarting the single gateway process.

## Endpoints

- `GET /admin/policy` returns the active policy, version, and version metadata.
- `PUT /admin/policy` accepts `{"policy": { ... }}` or the policy object directly.
- `POST /admin/policy/rollback/{version}` activates an available older version as a new version.

All require an enabled admin credential with the `admin` role. Updates are parsed, checked for known agents, assigned servers, valid schemas, non-empty methods, and `default_action: deny`. A valid snapshot is copied and swapped as one reference; requests cannot observe a partially edited policy object. Existing call-time checks use the currently active version.

The history contains at most 100 versions and is memory-only. A successful runtime change does not rewrite the YAML file. Persist the same reviewed policy in deployment configuration before restarting or the runtime change will be lost.

The current API is whole-snapshot replacement plus rollback. It does not provide separate create/update/delete/enable endpoints for individual policy entities or expose a durable change approval workflow. Policy update and rollback actors and version numbers are recorded in admin audit events.
