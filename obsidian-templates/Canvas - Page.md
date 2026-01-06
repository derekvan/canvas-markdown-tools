<%*
// Canvas Page Template
const title = await tp.system.prompt("Page title");
if (!title) return;
-%>
## [page] <% title %>
<% tp.file.cursor() %>
