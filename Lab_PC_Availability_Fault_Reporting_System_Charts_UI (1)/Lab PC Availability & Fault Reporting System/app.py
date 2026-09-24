from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)
import sqlite3
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

DATABASE = "lab_pc.db"


def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    connection = get_db_connection()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student'
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS pcs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_number TEXT NOT NULL,
            lab_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available',
            problem_description TEXT DEFAULT '',
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS fault_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id INTEGER NOT NULL,
            student_name TEXT NOT NULL,
            student_email TEXT NOT NULL,
            description TEXT NOT NULL,
            report_status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pc_id) REFERENCES pcs(id)
        )
    """)

    admin_exists = connection.execute(
        "SELECT * FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin_exists:
        connection.execute(
            """
            INSERT INTO users (username, password, role)
            VALUES (?, ?, ?)
            """,
            (
                "admin",
                generate_password_hash("admin123"),
                "management"
            )
        )

    pc_count = connection.execute(
        "SELECT COUNT(*) AS count FROM pcs"
    ).fetchone()["count"]

    if pc_count == 0:
        sample_pcs = [
            ("PC-01", "Computer Lab 1", "Available", ""),
            ("PC-02", "Computer Lab 1", "Available", ""),
            ("PC-03", "Computer Lab 1", "Faulty", "Keyboard not working"),
            ("PC-04", "Computer Lab 1", "In Use", ""),
            ("PC-05", "Computer Lab 2", "Available", ""),
            ("PC-06", "Computer Lab 2", "Under Maintenance", "Operating system update"),
            ("PC-07", "Computer Lab 2", "Available", ""),
            ("PC-08", "Computer Lab 2", "Faulty", "Monitor not displaying")
        ]

        connection.executemany(
            """
            INSERT INTO pcs
            (pc_number, lab_name, status, problem_description)
            VALUES (?, ?, ?, ?)
            """,
            sample_pcs
        )

    connection.commit()
    connection.close()


def management_required(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("role") != "management":
            flash("Please log in as management.", "danger")
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return decorated_function


@app.route("/")
def index():
    lab_filter = request.args.get("lab", "")
    status_filter = request.args.get("status", "")

    connection = get_db_connection()

    query = "SELECT * FROM pcs WHERE 1=1"
    parameters = []

    if lab_filter:
        query += " AND lab_name = ?"
        parameters.append(lab_filter)

    if status_filter:
        query += " AND status = ?"
        parameters.append(status_filter)

    query += " ORDER BY lab_name, pc_number"

    pcs = connection.execute(query, parameters).fetchall()

    labs = connection.execute(
        "SELECT DISTINCT lab_name FROM pcs ORDER BY lab_name"
    ).fetchall()

    summary = connection.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Available' THEN 1 ELSE 0 END) AS available,
            SUM(CASE WHEN status = 'Faulty' THEN 1 ELSE 0 END) AS faulty,
            SUM(CASE WHEN status = 'In Use' THEN 1 ELSE 0 END) AS in_use,
            SUM(CASE WHEN status = 'Under Maintenance' THEN 1 ELSE 0 END)
                AS maintenance
        FROM pcs
    """).fetchone()

    connection.close()

    return render_template(
        "index.html",
        pcs=pcs,
        labs=labs,
        summary=summary,
        selected_lab=lab_filter,
        selected_status=status_filter
    )


@app.route("/report/<int:pc_id>", methods=["GET", "POST"])
def report_fault(pc_id):
    connection = get_db_connection()
    pc = connection.execute(
        "SELECT * FROM pcs WHERE id = ?",
        (pc_id,)
    ).fetchone()

    if not pc:
        connection.close()
        flash("PC not found.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        student_name = request.form["student_name"].strip()
        student_email = request.form["student_email"].strip()
        description = request.form["description"].strip()

        if not student_name or not student_email or not description:
            flash("All fields are required.", "danger")
            connection.close()
            return render_template("report.html", pc=pc)

        connection.execute(
            """
            INSERT INTO fault_reports
            (pc_id, student_name, student_email, description)
            VALUES (?, ?, ?, ?)
            """,
            (pc_id, student_name, student_email, description)
        )

        connection.execute(
            """
            UPDATE pcs
            SET status = 'Faulty',
                problem_description = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (description, pc_id)
        )

        connection.commit()
        connection.close()

        flash("Fault report submitted successfully.", "success")
        return redirect(url_for("index"))

    connection.close()
    return render_template("report.html", pc=pc)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        connection = get_db_connection()
        user = connection.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        connection.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]

            return redirect(url_for("admin_dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/admin")
@management_required
def admin_dashboard():
    connection = get_db_connection()

    pcs = connection.execute("""
        SELECT * FROM pcs
        ORDER BY lab_name, pc_number
    """).fetchall()

    reports = connection.execute("""
        SELECT
            fault_reports.*,
            pcs.pc_number,
            pcs.lab_name
        FROM fault_reports
        JOIN pcs ON fault_reports.pc_id = pcs.id
        ORDER BY fault_reports.created_at DESC
    """).fetchall()

    chart = connection.execute("""
        SELECT
            SUM(CASE WHEN status = 'Available' THEN 1 ELSE 0 END) AS available,
            SUM(CASE WHEN status = 'Faulty' THEN 1 ELSE 0 END) AS faulty,
            SUM(CASE WHEN status = 'In Use' THEN 1 ELSE 0 END) AS in_use,
            SUM(CASE WHEN status = 'Under Maintenance' THEN 1 ELSE 0 END) AS maintenance
        FROM pcs
    """).fetchone()

    connection.close()

    return render_template(
        "admin.html",
        pcs=pcs,
        reports=reports,
        chart=chart
    )


@app.route("/admin/pc/<int:pc_id>/update", methods=["POST"])
@management_required
def update_pc(pc_id):
    status = request.form["status"]
    problem_description = request.form.get(
        "problem_description",
        ""
    ).strip()

    allowed_statuses = [
        "Available",
        "Faulty",
        "In Use",
        "Under Maintenance"
    ]

    if status not in allowed_statuses:
        flash("Invalid PC status.", "danger")
        return redirect(url_for("admin_dashboard"))

    connection = get_db_connection()

    connection.execute(
        """
        UPDATE pcs
        SET status = ?,
            problem_description = ?,
            last_updated = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, problem_description, pc_id)
    )

    connection.commit()
    connection.close()

    flash("PC status updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/report/<int:report_id>/resolve", methods=["POST"])
@management_required
def resolve_report(report_id):
    connection = get_db_connection()

    connection.execute(
        """
        UPDATE fault_reports
        SET report_status = 'Resolved'
        WHERE id = ?
        """,
        (report_id,)
    )

    connection.commit()
    connection.close()

    flash("Fault report marked as resolved.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)
