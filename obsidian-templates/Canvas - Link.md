<%*
// Canvas External Link Template
const title = await tp.system.prompt("Link title");
if (!title) return;
const url = await tp.system.prompt("URL (include https://)");
if (!url) return;
-%>
## [link] <% title %>
url: <% url %>
