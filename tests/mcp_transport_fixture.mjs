// Exercise the same installed transport used by Revamp; loopback only.
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const sdkRoot = process.argv[2];
const { McpServer } = await import(pathToFileURL(resolve(sdkRoot, 'dist/esm/server/mcp.js')));
const { WebStandardStreamableHTTPServerTransport } = await import(pathToFileURL(resolve(sdkRoot, 'dist/esm/server/webStandardStreamableHttp.js')));

const http = createServer(async (req, res) => {
  if (req.method !== 'POST' || req.url !== '/api/make/mcp' || req.headers.authorization !== 'Bearer fixture-access') {
    res.writeHead(401).end();
    return;
  }
  const server = new McpServer({ name: 'revamp-dify-local-fixture', version: '1' });
  server.registerTool('list_projects', { inputSchema: {} }, async () => ({
    content: [{ type: 'text', text: 'No fixture projects.' }],
    structuredContent: { projects: [] },
  }));
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined, enableJsonResponse: true,
  });
  try {
    const parts = [];
    for await (const chunk of req) parts.push(chunk);
    await server.connect(transport);
    const response = await transport.handleRequest(new Request(`http://127.0.0.1${req.url}`, {
      method: req.method, headers: req.headers, body: Buffer.concat(parts),
    }));
    res.writeHead(response.status, Object.fromEntries(response.headers));
    res.end(await response.text());
  } catch {
    res.writeHead(500).end();
  } finally {
    await server.close();
  }
});
http.listen(0, '127.0.0.1', () => console.log(http.address().port));
