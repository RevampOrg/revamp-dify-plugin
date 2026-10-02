# Revamp

Create or redesign websites and build web apps from your Dify workflows.
Describe what you need, follow progress, and keep improving the same project.
Continue in [Revamp](https://revamp.dev) for visual editing and publishing.

This plugin connects to the existing Revamp service. You need a Revamp account
with enough credits for generation and edits. Installing or connecting the
plugin does not start generation. Existing plan limits and permissions apply.
The plugin does not require a separate model connection or an open Studio tab.

## Connect your account

Install the plugin, open **Tools → Revamp**, and select the account connection
option. Sign in to Revamp and approve the connection. Select that credential
for your workflow or agent. Each user connects their own Revamp account.

The Dify instance administrator must configure its Revamp OAuth client before
users can connect. Dify Cloud may provide this configuration after marketplace
review; marketplace installation alone does not guarantee it is preconfigured.

### Administrator setup

1. Copy the exact callback URL displayed by Dify's Revamp OAuth client settings.
   It has the form
   `https://<console-api-host>/console/api/oauth/plugin/<provider>/tool/callback`.
   Use the actual value from your instance, including the provider identifier.
2. Register a confidential client at
   `https://app.revamp.dev/api/auth/mcp/register`, with these fields:

   ```json
   {
     "client_name": "Revamp for Dify",
     "redirect_uris": ["<exact Dify callback URL>"],
     "grant_types": ["authorization_code", "refresh_token"],
     "response_types": ["code"],
     "token_endpoint_auth_method": "client_secret_basic",
     "scope": "openid email offline_access"
   }
   ```

3. Save the returned client ID and client secret in Dify's OAuth client settings.
   Do not put them in a workflow, source repository, screenshot or public issue.
4. Connect a Revamp account using the normal authorization button.

Client registration does not grant access to any account. Access starts only
after that account signs in and approves the connection. Tokens remain in
Dify's credential store, and Dify calls the refresh handler when they expire.
To disconnect, remove the credential and revoke the corresponding connection
in Revamp. Existing projects remain in Revamp.

## Actions

| Action | Purpose |
| --- | --- |
| Create a website | Start a website from instructions. |
| Redesign a website | Start a redesign from a public website URL and optional goals. |
| Build a web app | Start an interactive web app, such as a portal or booking flow. |
| Check project | Read the requested generation turn, its reply and available preview. |
| Improve a project | Request a change to an existing project. |
| List projects | Find up to 30 recent projects owned by the connected account. |
| List clients | Find existing agency client folders; empty for other accounts. |

Creation and editing use Revamp credits and can change project content. Read
actions do not start generation or builds. A redesign creates a new Revamp
project; it does not change the original website. This release accepts text
instructions and public website URLs. Add image references directly in Revamp.

### Example workflow

1. Feed a project name and instructions into **Create a website**.
2. Set **Request reference** to a stable source-record ID plus action version.
3. Save the returned `projectId`, `submissionId` and `studioUrl`.
4. In a later workflow step or execution, pass those IDs to **Check project**.
5. Show the `reply` and available `previewUrl`, or continue in `studioUrl`.

A request reference identifies one requested action. Reuse it only to retry
the same inputs. Use a new reference for a new website or another edit. For
agent use, choose a fresh UUID once per requested action and retain it on retry.
This prevents a transport retry from creating another project. Never retry an
uncertain creation with a new reference just to check progress.

`status` describes the agent turn, not build success. A completed turn does not
prove that a new preview was built. `previewUrl` is the latest available preview
and may predate a requested edit; inspect the reply before presenting it as the
result. A null preview means no URL was available at that check. Do not rapidly
poll in an unbounded loop. Generation can continue after the tool returns.

## Privacy and support

The plugin sends only the selected tool inputs and account connection requests
to Revamp. See [PRIVACY.md](PRIVACY.md) and [Revamp's privacy policy](https://revamp.dev/privacy).

Maintained by **Revamp Staff**. Website: [revamp.dev](https://revamp.dev).
Support: **contact@revamp.dev**.

Source repository: [RevampOrg/revamp-dify-plugin](https://github.com/RevampOrg/revamp-dify-plugin).
