<%*
// Canvas Discussion Template
const title = await tp.system.prompt("Discussion title");
if (!title) return;

// Threaded replies (default true)
const threaded = await tp.system.suggester(
    ["Threaded (allow nested replies)", "Focused (single level only)"],
    [true, false],
    false,
    "Reply style"
);

// Require initial post
const requireInitialPost = await tp.system.suggester(
    ["No (can view others first)", "Yes (must post before viewing)"],
    [false, true],
    false,
    "Require initial post?"
);

// Graded?
const isGraded = await tp.system.suggester(
    ["Not graded", "Graded"],
    [false, true],
    false,
    "Is this graded?"
);

let points = "0";
let gradeDisplay = "complete_incomplete";
let dueLine = "";

if (isGraded) {
    // Points
    const pointsInput = await tp.system.prompt("Points (leave empty for 0)", "0");
    points = pointsInput || "0";
    
    // Grade display
    gradeDisplay = await tp.system.suggester(
        ["Complete/Incomplete", "Points", "Not Graded"],
        ["complete_incomplete", "points", "not_graded"],
        false,
        "Grade display"
    );
    
    // Due date
    const dueDate = await tp.system.prompt("Due date (YYYY-MM-DD or Jan 15, 2026)", tp.date.now("YYYY-MM-DD"));
    const dueTime = await tp.system.prompt("Due time", "11:59pm");
    if (dueDate) {
        dueLine = `due: ${dueDate} ${dueTime}\n`;
    }
}

// Build output
let output = `## [discussion] ${title}\n`;

// Only output non-default values
if (requireInitialPost) {
    output += `require_initial_post: true\n`;
}
if (!threaded) {
    output += `threaded: false\n`;
}
if (isGraded) {
    output += `graded: true\n`;
    if (points !== "0") {
        output += `points: ${points}\n`;
    }
    if (dueLine) {
        output += dueLine;
    }
    if (gradeDisplay && gradeDisplay !== "complete_incomplete") {
        output += `grade_display: ${gradeDisplay}\n`;
    }
}
output += `---\n`;

tR += output;
-%>
<% tp.file.cursor() %>
