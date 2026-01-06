<%*
// Canvas Assignment Template
const title = await tp.system.prompt("Assignment title");
if (!title) return;

// Points
const pointsInput = await tp.system.prompt("Points (leave empty for 0)", "0");
const points = pointsInput || "0";

// Grade display
const gradeDisplay = await tp.system.suggester(
    ["Complete/Incomplete", "Points", "Not Graded"],
    ["complete_incomplete", "points", "not_graded"],
    false,
    "Grade display"
);

// Submission types
const submissionType = await tp.system.suggester(
    ["Online Text Entry", "File Upload", "Text + File Upload", "URL", "Media Recording", "No Submission", "On Paper"],
    ["online_text_entry", "online_upload", "online_text_entry, online_upload", "online_url", "media_recording", "none", "on_paper"],
    false,
    "Submission type"
);

// Due date
const hasDueDate = await tp.system.suggester(
    ["Yes, add due date", "No due date"],
    [true, false],
    false,
    "Add due date?"
);

let dueLine = "";
if (hasDueDate) {
    const dueDate = await tp.system.prompt("Due date (YYYY-MM-DD or Jan 15, 2026)", tp.date.now("YYYY-MM-DD"));
    const dueTime = await tp.system.prompt("Due time", "11:59pm");
    if (dueDate) {
        dueLine = `due: ${dueDate} ${dueTime}\n`;
    }
}

// Build output
let output = `## [assignment] ${title}\n`;
if (points !== "0") {
    output += `points: ${points}\n`;
}
if (dueLine) {
    output += dueLine;
}
if (gradeDisplay && gradeDisplay !== "complete_incomplete") {
    output += `grade_display: ${gradeDisplay}\n`;
}
if (submissionType && submissionType !== "online_text_entry") {
    output += `submission_types: ${submissionType}\n`;
}
output += `---\n`;

tR += output;
-%>
<% tp.file.cursor() %>
