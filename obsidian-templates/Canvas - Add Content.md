<%*
// Canvas Content - Quick Add
// Choose which type of content to add

const contentType = await tp.system.suggester(
    ["📁 Module", "📝 Header", "📄 Page", "🔗 External Link", "📎 File", "📋 Assignment", "💬 Discussion"],
    ["module", "header", "page", "link", "file", "assignment", "discussion"],
    false,
    "What type of content?"
);

if (!contentType) return;

// ============================================================================
// MODULE
// ============================================================================
if (contentType === "module") {
    const title = await tp.system.prompt("Module title (e.g., Week 1 - Jan 13 & 15)");
    if (!title) return;
    tR += `# ${title}\n\n`;
}

// ============================================================================
// HEADER
// ============================================================================
else if (contentType === "header") {
    const title = await tp.system.prompt("Header text");
    if (!title) return;
    tR += `## [header] ${title}\n`;
}

// ============================================================================
// PAGE
// ============================================================================
else if (contentType === "page") {
    const title = await tp.system.prompt("Page title");
    if (!title) return;
    tR += `## [page] ${title}\n`;
}

// ============================================================================
// LINK
// ============================================================================
else if (contentType === "link") {
    const title = await tp.system.prompt("Link title");
    if (!title) return;
    const url = await tp.system.prompt("URL (include https://)");
    if (!url) return;
    tR += `## [link] ${title}\nurl: ${url}\n`;
}

// ============================================================================
// FILE
// ============================================================================
else if (contentType === "file") {
    const title = await tp.system.prompt("Display title (e.g., Reading: Chapter 1)");
    if (!title) return;
    const filename = await tp.system.prompt("Filename in Canvas Files (e.g., chapter1.pdf)", title);
    
    let output = `## [file] ${title}\n`;
    if (filename && filename !== title) {
        output += `filename: ${filename}\n`;
    }
    tR += output;
}

// ============================================================================
// ASSIGNMENT
// ============================================================================
else if (contentType === "assignment") {
    const title = await tp.system.prompt("Assignment title");
    if (!title) return;

    const pointsInput = await tp.system.prompt("Points (leave empty for 0)", "0");
    const points = pointsInput || "0";

    const gradeDisplay = await tp.system.suggester(
        ["Complete/Incomplete", "Points", "Not Graded"],
        ["complete_incomplete", "points", "not_graded"],
        false,
        "Grade display"
    );

    const submissionType = await tp.system.suggester(
        ["Online Text Entry", "File Upload", "Text + File Upload", "URL", "Media Recording", "No Submission", "On Paper"],
        ["online_text_entry", "online_upload", "online_text_entry, online_upload", "online_url", "media_recording", "none", "on_paper"],
        false,
        "Submission type"
    );

    const hasDueDate = await tp.system.suggester(
        ["Yes, add due date", "No due date"],
        [true, false],
        false,
        "Add due date?"
    );

    let dueLine = "";
    if (hasDueDate) {
        const dueDate = await tp.system.prompt("Due date (YYYY-MM-DD)", tp.date.now("YYYY-MM-DD"));
        const dueTime = await tp.system.prompt("Due time", "11:59pm");
        if (dueDate) {
            dueLine = `due: ${dueDate} ${dueTime}\n`;
        }
    }

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
}

// ============================================================================
// DISCUSSION
// ============================================================================
else if (contentType === "discussion") {
    const title = await tp.system.prompt("Discussion title");
    if (!title) return;

    const threaded = await tp.system.suggester(
        ["Threaded (allow nested replies)", "Focused (single level only)"],
        [true, false],
        false,
        "Reply style"
    );

    const requireInitialPost = await tp.system.suggester(
        ["No (can view others first)", "Yes (must post before viewing)"],
        [false, true],
        false,
        "Require initial post?"
    );

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
        const pointsInput = await tp.system.prompt("Points (leave empty for 0)", "0");
        points = pointsInput || "0";
        
        gradeDisplay = await tp.system.suggester(
            ["Complete/Incomplete", "Points", "Not Graded"],
            ["complete_incomplete", "points", "not_graded"],
            false,
            "Grade display"
        );
        
        const dueDate = await tp.system.prompt("Due date (YYYY-MM-DD)", tp.date.now("YYYY-MM-DD"));
        const dueTime = await tp.system.prompt("Due time", "11:59pm");
        if (dueDate) {
            dueLine = `due: ${dueDate} ${dueTime}\n`;
        }
    }

    let output = `## [discussion] ${title}\n`;
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
}
-%>
<% tp.file.cursor() %>
