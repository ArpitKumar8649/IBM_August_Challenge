const http = require('http');
const https = require('https');

const TARGET_API = 'https://api.clusterprotocol.ai/v1/chat/completions';
const PORT = 3000;

function translateToOpenAI(anthropicReq) {
    const openaiReq = {
        model: anthropicReq.model || 'kimi-k3',
        messages: [],
        stream: anthropicReq.stream || false,
        temperature: anthropicReq.temperature,
        max_tokens: anthropicReq.max_tokens,
    };

    if (anthropicReq.system) {
        let systemContent = Array.isArray(anthropicReq.system)
            ? anthropicReq.system.map(b => b.text).join('\n')
            : anthropicReq.system;
        openaiReq.messages.push({ role: 'system', content: systemContent });
    }

    for (const msg of (anthropicReq.messages || [])) {
        const role = msg.role;

        if (typeof msg.content === 'string') {
            openaiReq.messages.push({ role, content: msg.content });
            continue;
        }

        let textContent = '';
        let toolCalls = [];
        let toolResults = [];

        for (const block of (msg.content || [])) {
            if (block.type === 'text') {
                textContent += block.text;
            } else if (block.type === 'tool_use') {
                toolCalls.push({
                    id: block.id,
                    type: 'function',
                    function: {
                        name: block.name,
                        arguments: JSON.stringify(block.input)
                    }
                });
            } else if (block.type === 'tool_result') {
                toolResults.push({
                    name: block.tool_use_id,
                    content: typeof block.content === 'string' ? block.content : JSON.stringify(block.content),
                    is_error: block.is_error
                });
            }
        }

        if (role === 'assistant') {
            const outMsg = { role: 'assistant', content: textContent || null };
            if (toolCalls.length > 0) outMsg.tool_calls = toolCalls;
            openaiReq.messages.push(outMsg);
        } else if (role === 'user' && toolResults.length > 0) {
            // Combine all tool results in this batch into a SINGLE user message
            // to prevent consecutive user message truncation issues upstream
            let combinedContent = "";
            for (const tr of toolResults) {
                let contentStr = tr.content;
                if (tr.is_error) contentStr = `Error: ${contentStr}`;
                combinedContent += `[Tool Result for ${tr.name}]:\n${contentStr}\n\n`;
            }
            if (textContent) {
                combinedContent += textContent;
            }

            openaiReq.messages.push({
                role: 'user',
                content: combinedContent.trim()
            });
        } else {
            openaiReq.messages.push({ role, content: textContent });
        }
    }

    if (anthropicReq.tools && anthropicReq.tools.length > 0) {
        openaiReq.tools = anthropicReq.tools.map(t => ({
            type: 'function',
            function: {
                name: t.name,
                description: t.description,
                parameters: t.input_schema
            }
        }));
    }

    return openaiReq;
}

const server = http.createServer((req, res) => {
    // Anthropic API endpoints
    if (req.method !== 'POST' || !req.url.includes('/v1/messages')) {
        res.writeHead(404);
        return res.end('Not Found');
    }

    let body = '';
    req.on('data', chunk => body += chunk.toString());
    req.on('end', () => {
        try {
            const anthropicReq = JSON.parse(body);
            const openaiReq = translateToOpenAI(anthropicReq);

            console.log("\n[PROXY] -> Sending to Cluster Protocol (stream:", openaiReq.stream, ")");

            const reqUrl = new URL(TARGET_API);
            const options = {
                hostname: reqUrl.hostname,
                path: reqUrl.pathname,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': req.headers['authorization'] || '',
                    'User-Agent': 'curl/8.5.0',
                    'Accept': '*/*'
                }
            };

            const proxyReq = https.request(options, (proxyRes) => {
                if (openaiReq.stream) {
                    res.writeHead(200, {
                        'Content-Type': 'text/event-stream',
                        'Cache-Control': 'no-cache',
                        'Connection': 'keep-alive'
                    });

                    // Send Anthropic message_start
                    res.write(`event: message_start\ndata: ${JSON.stringify({
                        type: "message_start",
                        message: { id: "msg_1", type: "message", role: "assistant", content: [], model: openaiReq.model, stop_reason: null, stop_sequence: null, usage: { input_tokens: 0, output_tokens: 0 } }
                    })}\n\n`);

                    let contentBlockIndex = 0;
                    let currentToolCall = null;
                    let buffer = '';

                    proxyRes.on('data', chunk => {
                        buffer += chunk.toString();
                        let lines = buffer.split('\n');
                        buffer = lines.pop(); // Keep incomplete line

                        for (let line of lines) {
                            line = line.trim();
                            if (!line.startsWith('data: ')) continue;
                            const dataStr = line.substring(6).trim();
                            if (dataStr === '[DONE]') {
                                res.write(`event: message_stop\ndata: {"type":"message_stop"}\n\n`);
                                res.end();
                                continue;
                            }

                            try {
                                const o = JSON.parse(dataStr);
                                if (o.error) {
                                    console.log("[PROXY] API ERROR:", o.error);
                                    res.write(`event: error\ndata: ${JSON.stringify(o.error)}\n\n`);
                                    res.end();
                                    continue;
                                }
                                const delta = o.choices?.[0]?.delta;
                                if (!delta) continue;

                                // 1. Text Delta
                                if (delta.content) {
                                    if (contentBlockIndex === 0 && !currentToolCall) {
                                        res.write(`event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`);
                                        contentBlockIndex = 1;
                                    }
                                    res.write(`event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text: delta.content } })}\n\n`);
                                }

                                // 2. Tool Call Delta
                                if (delta.tool_calls) {
                                    for (const tc of delta.tool_calls) {
                                        if (tc.id) { // New tool call started
                                            currentToolCall = tc;
                                            res.write(`event: content_block_start\ndata: ${JSON.stringify({
                                                type: "content_block_start",
                                                index: contentBlockIndex,
                                                content_block: { type: "tool_use", id: tc.id, name: tc.function.name, input: {} }
                                            })}\n\n`);
                                        } else if (tc.function?.arguments && currentToolCall) {
                                            // Tool argument streaming
                                            res.write(`event: content_block_delta\ndata: ${JSON.stringify({
                                                type: "content_block_delta",
                                                index: contentBlockIndex,
                                                delta: { type: "input_json_delta", partial_json: tc.function.arguments }
                                            })}\n\n`);
                                        }
                                    }
                                }

                                // 3. Finish Reason
                                if (o.choices?.[0]?.finish_reason) {
                                    const fr = o.choices[0].finish_reason;
                                    const stopReason = fr === 'tool_calls' ? 'tool_use' : 'end_turn';

                                    if (currentToolCall) {
                                        res.write(`event: content_block_stop\ndata: {"type":"content_block_stop","index":${contentBlockIndex}}\n\n`);
                                    } else if (contentBlockIndex > 0) {
                                        res.write(`event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n`);
                                    }

                                    res.write(`event: message_delta\ndata: ${JSON.stringify({
                                        type: "message_delta",
                                        delta: { stop_reason: stopReason, stop_sequence: null },
                                        usage: { output_tokens: o.usage?.completion_tokens || 0 }
                                    })}\n\n`);
                                }

                            } catch (e) {
                                // Ignore unparseable stream chunks
                            }
                        }
                    });

                    proxyRes.on('end', () => res.end());
                    return;
                }

                // --- NON-STREAMING FALLBACK ---
                let responseBody = '';
                proxyRes.on('data', chunk => responseBody += chunk.toString());
                proxyRes.on('end', () => {
                    try {
                        const openaiRes = JSON.parse(responseBody);
                        if (openaiRes.error) {
                            res.writeHead(proxyRes.statusCode, { 'Content-Type': 'application/json' });
                            return res.end(JSON.stringify({ type: 'error', error: openaiRes.error }));
                        }

                        const choice = openaiRes.choices[0];
                        const anthropicRes = {
                            id: openaiRes.id,
                            type: "message",
                            role: "assistant",
                            model: openaiRes.model,
                            content: [],
                            stop_reason: choice.finish_reason === 'tool_calls' ? 'tool_use' : 'end_turn',
                            stop_sequence: null,
                            usage: {
                                input_tokens: openaiRes.usage?.prompt_tokens || 0,
                                output_tokens: openaiRes.usage?.completion_tokens || 0
                            }
                        };

                        if (choice.message.content) {
                            anthropicRes.content.push({ type: 'text', text: choice.message.content });
                        }

                        if (choice.message.tool_calls) {
                            for (const tc of choice.message.tool_calls) {
                                anthropicRes.content.push({
                                    type: 'tool_use',
                                    id: tc.id,
                                    name: tc.function.name,
                                    input: JSON.parse(tc.function.arguments || '{}')
                                });
                            }
                        }

                        res.writeHead(200, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify(anthropicRes));
                    } catch (e) {
                        res.writeHead(500);
                        res.end(`Proxy Error: ${e.message}`);
                    }
                });
            });

            proxyReq.on('error', (e) => {
                console.error(e);
                res.writeHead(502);
                res.end(e.message);
            });

            proxyReq.write(JSON.stringify(openaiReq));
            proxyReq.end();

        } catch (e) {
            console.error(e);
            res.writeHead(400);
            res.end(`Bad Request: ${e.message}`);
        }
    });
});

server.listen(PORT, () => {
    console.log(`Anthropic -> Cluster Protocol Proxy running on http://localhost:${PORT}`);
});