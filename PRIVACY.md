# Revamp for Dify — Privacy

This plugin is maintained by Revamp Staff, contact@revamp.dev.

## Account connection

When you approve a Revamp connection, Dify stores the resulting access and
refresh tokens in its credential store. The plugin uses them to act on behalf
of that account. Revamp receives the account connection and authorization
requests. A read-only account identifier is used to scope retry references.
Tokens and client secrets are never included in tool outputs or plugin logs.
Your Dify instance administrator controls credential visibility and storage.

## Tool data

The plugin sends the instructions, website URL, project name, project and
submission IDs, request reference and optional client-folder ID needed for the
selected action to Revamp over HTTPS. Revamp processes generation requests using
its existing AI providers and project services. Responses can include project
names, agent replies, project progress, client folders and preview links. Only
invoke tools with content you are authorized to share.

The plugin does not send your entire Dify conversation, knowledge base,
unrelated workflow inputs or files. It does not maintain a separate copy of
your project data. Revamp stores project and conversation data to provide the
service under [Revamp's privacy policy](https://revamp.dev/privacy). Revamp does
not use customer data from this integration to train or improve AI models.

The plugin has no advertising trackers or separate analytics service. Dify and
Revamp may retain operational records according to their own policies.

## Disconnecting

Remove the credential in Dify and revoke the connection in Revamp to end access.
Disconnecting does not delete your existing Revamp projects. Contact
contact@revamp.dev for privacy or deletion requests.
