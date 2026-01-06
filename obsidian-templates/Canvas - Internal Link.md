<%*
// Canvas Internal Link - Insert a link to another Canvas item
// These get resolved to Canvas URLs when the course is built

const linkType = await tp.system.suggester(
    ["📄 Page", "📋 Assignment", "💬 Discussion", "📎 File"],
    ["Page", "Assignment", "Discussion", "File"],
    false,
    "Link to what type of content?"
);

if (!linkType) return;

let placeholder = "";
if (linkType === "Page") {
    placeholder = "Page Title";
} else if (linkType === "Assignment") {
    placeholder = "Assignment Title";
} else if (linkType === "Discussion") {
    placeholder = "Discussion Title";
} else if (linkType === "File") {
    placeholder = "filename.pdf";
}

const name = await tp.system.prompt(`Enter the ${linkType.toLowerCase()} name/title`, placeholder);
if (!name) return;

tR += `[[${linkType}:${name}]]`;
-%>
