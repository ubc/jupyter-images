#!/usr/bin/env python3
import sys

PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"
TEMPLATE_DIR = f"/opt/conda/lib/python{PYTHON_VERSION}/site-packages/nbgrader/server_extensions/formgrader/templates/"
APIHANDLERS = f"/opt/conda/lib/python{PYTHON_VERSION}/site-packages/nbgrader/server_extensions/formgrader/apihandlers.py"
JS_DIR = f"/opt/conda/lib/python{PYTHON_VERSION}/site-packages/nbgrader/server_extensions/formgrader/static/js/"


def patch_file(path, old, new, label):
    try:
        with open(path) as f:
            content = f.read()
        if old not in content:
            print(f"[SKIP] {label}: string not found (already patched or version mismatch)")
            return
        with open(path, "w") as f:
            f.write(content.replace(old, new))
        print(f"[OK]   {label}: patched successfully")
    except FileNotFoundError:
        print(f"[WARN] {label}: file not found at {path}")
    except Exception as e:
        print(f"[ERROR] {label}: {e}")


# 1. Remove Edit Student column header from manage_students.tpl
patch_file(
    path=TEMPLATE_DIR + "manage_students.tpl",
    old='  <th class="text-center no-sort">Edit Student</th>',
    new='{# Edit Student column disabled - use ngshare-course-management CLI #}',
    label="manage_students.tpl: remove Edit Student column header"
)

# 2. Remove Add new student footer from manage_students.tpl
patch_file(
    path=TEMPLATE_DIR + "manage_students.tpl",
    old="""  <td colspan="5">
    <span class="glyphicon glyphicon-plus" aria-hidden="true"></span>
    <a href="#" onClick="createStudentModal();">Add new student...</a>
  </td>""",
    new="""  <td colspan="5">
    {# Add new student disabled - use ngshare-course-management CLI #}
  </td>""",
    label="manage_students.tpl: remove Add new student button"
)

# 3. Block PUT /api/student in apihandlers.py
patch_file(
    path=APIHANDLERS,
    old="""    @web.authenticated
    def put(self, student_id):
        student = {""",
    new="""    @web.authenticated
    def put(self, student_id):
        raise web.HTTPError(403, reason="Use ngshare-course-management CLI instead.")
    def put_DISABLED(self, student_id):
        student = {""",
    label="apihandlers.py: block PUT /api/student"
)

# 4. Remove Edit button from manage_students.js
patch_file(
    path=JS_DIR + "manage_students.js",
    old="""        // edit metadata
        this.$edit.append($("<a/>")
            .attr("href", "#")
            .click(_.bind(this.openModal, this))
            .append($("<span/>")
                .addClass("glyphicon glyphicon-pencil")
                .attr("aria-hidden", "true")));""",
    new="""        // edit metadata disabled - use ngshare-course-management CLI""",
    label="manage_students.js: remove Edit button"
)

# 5. Disable openModal function in manage_students.js
patch_file(
    path=JS_DIR + "manage_students.js",
    old="""    openModal: function () {
        var body = $("<table/>").addClass("table table-striped form-table");
        var tablebody = $("<tbody/>");
        body.append(tablebody);
        var id = $("<tr/>");
        tablebody.append(id);
        id.append($("<td/>").addClass("align-middle").text("Student ID"));
        id.append($("<td/>").append($("<input/>")
            .addClass("modal-id")
            .attr("type", "text")
            .attr("disabled", "disabled")));

        var first_name = $("<tr/>");
        tablebody.append(first_name);
        first_name.append($("<td/>").addClass("align-middle").text("First name (optional)"));
        first_name.append($("<td/>").append($("<input/>").addClass("modal-first-name").attr("type", "text")));

        var last_name = $("<tr/>");
        tablebody.append(last_name);
        last_name.append($("<td/>").addClass("align-middle").text("Last name (optional)"));
        last_name.append($("<td/>").append($("<input/>").addClass("modal-last-name").attr("type", "text")));

        var email = $("<tr/>");
        tablebody.append(email);
        email.append($("<td/>").addClass("align-middle").text("Email (optional)"));
        email.append($("<td/>").append($("<input/>").addClass("modal-email").attr("type", "text")));

        var footer = $("<div/>");
        footer.append($("<button/>")
            .addClass("btn btn-primary save")
            .attr("type", "button")
            .text("Save"));
        footer.append($("<button/>")
            .addClass("btn btn-danger")
            .attr("type", "button")
            .attr("data-dismiss", "modal")
            .text("Cancel"));

        this.$modal = createModal("edit-student-modal", "Editing " + this.model.get("id"), body, footer);
        this.$modal.find("input.modal-id").val(this.model.get("id"));
        this.$modal_first_name = this.$modal.find("input.modal-first-name");
        this.$modal_first_name.val(this.model.get("first_name"));
        this.$modal_last_name = this.$modal.find("input.modal-last-name");
        this.$modal_last_name.val(this.model.get("last_name"));
        this.$modal_email = this.$modal.find("input.modal-email");
        this.$modal_email.val(this.model.get("email"));
        this.$modal_save = this.$modal.find("button.save");
        this.$modal_save.click(_.bind(this.save, this));
    },""",
    new="""    openModal: function () {
        // disabled - use ngshare-course-management CLI
    },""",
    label="manage_students.js: disable openModal function"
)

print("Done.")
