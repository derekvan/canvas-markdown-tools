<%*
const title = await tp.system.prompt("Display title (e.g., Reading: Chapter 1)");
if (!title) return;
const filename = await tp.system.prompt("Filename in Canvas Files (e.g., chapter1.pdf)", title);

let output = `## [file] ${title}\n`;
if (filename && filename !== title) {
    output += `filename: ${filename}\n`;
}
tR += output;
-%>
<% tp.file.cursor() %>
