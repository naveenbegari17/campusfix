import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash
from db import get_db, init_db, assign_department, analyze_issue_with_ai

app = Flask(__name__)
app.secret_key = 'campusfix_dev_secret_key_change_in_production'

# Initialize database on startup
with app.app_context():
    init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('login'))
            if session.get('role') not in allowed_roles:
                flash('You do not have permission to access that section.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Please enter both username and password.', 'danger')
            return render_template('login.html')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['department'] = user['department']
            flash(f"Welcome back, {user['full_name']}!", 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password. Please try again.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    priority_filter = request.args.get('priority', '').strip()
    dept_filter = request.args.get('department', '').strip()

    role = session.get('role')
    user_id = session.get('user_id')
    user_dept = session.get('department')

    conn = get_db()
    cursor = conn.cursor()

    # Base query
    query = 'SELECT * FROM issues WHERE 1=1'
    params = []

    # STRICT DATA ACCESS RULES:
    # 1. Students and Faculty: ONLY see issues they themselves raised.
    # 2. Staff: ONLY see issues assigned to their specific department (e.g. Plumber sees ONLY Plumbing Maintenance).
    # 3. Admin: Can see everything.
    if role in ['student', 'faculty']:
        query += ' AND reported_by_id = ?'
        params.append(user_id)
    elif role == 'staff':
        query += ' AND assigned_department = ?'
        params.append(user_dept)
    # Admin has no restriction

    if search:
        query += ' AND (title LIKE ? OR description LIKE ? OR location LIKE ?)'
        like_str = f'%{search}%'
        params.extend([like_str, like_str, like_str])

    if status_filter:
        query += ' AND status = ?'
        params.append(status_filter)

    if priority_filter:
        query += ' AND priority = ?'
        params.append(priority_filter)

    # Department filter allowed only for Admin
    if role == 'admin' and dept_filter:
        query += ' AND assigned_department = ?'
        params.append(dept_filter)

    query += ' ORDER BY id DESC'
    cursor.execute(query, params)
    issues = cursor.fetchall()

    # Statistics Calculation strictly scoped to the user's allowed data
    stats_query = 'SELECT status, COUNT(*) as count FROM issues WHERE 1=1'
    stats_params = []
    if role in ['student', 'faculty']:
        stats_query += ' AND reported_by_id = ?'
        stats_params.append(user_id)
    elif role == 'staff':
        stats_query += ' AND assigned_department = ?'
        stats_params.append(user_dept)

    stats_query += ' GROUP BY status'
    cursor.execute(stats_query, stats_params)
    status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

    total_issues = sum(status_counts.values())
    open_issues = status_counts.get('Open', 0)
    in_progress_issues = status_counts.get('In Progress', 0)
    resolved_issues = status_counts.get('Resolved', 0)

    # Departments list for admin filters and reassignments
    cursor.execute('SELECT DISTINCT assigned_department FROM issues WHERE assigned_department IS NOT NULL')
    db_depts = [r['assigned_department'] for r in cursor.fetchall()]
    all_depts = list(set(db_depts + ['Electrical Maintenance', 'Civil & Facilities', 'Plumbing Maintenance', 'IT Support', 'Admin Review']))
    all_depts.sort()

    conn.close()

    return render_template(
        'dashboard.html',
        issues=issues,
        total_issues=total_issues,
        open_issues=open_issues,
        in_progress_issues=in_progress_issues,
        resolved_issues=resolved_issues,
        all_depts=all_depts,
        search=search,
        status_filter=status_filter,
        priority_filter=priority_filter,
        dept_filter=dept_filter
    )

@app.route('/raise-issue', methods=['GET', 'POST'])
@login_required
def raise_issue():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        location = request.form.get('location', '').strip()
        priority = request.form.get('priority', 'Medium').strip()

        if not title or not description or not location:
            flash('Please fill in all required fields (Title, Description, Location).', 'danger')
            return render_template('raise_issue.html')

        # AI Agent Problem Analysis and Automatic Department Routing
        assigned_dept, confidence, ai_reasoning = analyze_issue_with_ai(title, description, category)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO issues (
                title, description, category, location, priority,
                status, assigned_department, ai_reasoning, reported_by_id, reported_by_name, reported_by_role
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            title, description, category, location, priority,
            'Open', assigned_dept, ai_reasoning, session['user_id'], session['full_name'], session['role']
        ))
        issue_id = cursor.lastrowid
        conn.commit()
        conn.close()

        flash(f'Issue #{issue_id} submitted! AI Agent classified it ({confidence}% confidence) to: {assigned_dept}', 'success')
        return redirect(url_for('issue_detail', issue_id=issue_id))

    return render_template('raise_issue.html')

@app.route('/issue/<int:issue_id>/delete', methods=['POST'])
@login_required
def delete_issue(issue_id):
    role = session.get('role')

    # STRICT ACCESS: Only Admin can delete issues
    if role != 'admin':
        flash('Unauthorized: Only administrators are permitted to delete issues.', 'danger')
        return redirect(url_for('dashboard'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM issues WHERE id = ?', (issue_id,))
    issue = cursor.fetchone()

    if not issue:
        conn.close()
        flash('Issue not found.', 'danger')
        return redirect(url_for('dashboard'))

    cursor.execute('DELETE FROM issues WHERE id = ?', (issue_id,))
    conn.commit()
    conn.close()

    flash(f'Issue #{issue_id} has been permanently deleted by administrator.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/issue/<int:issue_id>')
@login_required
def issue_detail(issue_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM issues WHERE id = ?', (issue_id,))
    issue = cursor.fetchone()
    conn.close()

    if not issue:
        flash('Issue not found.', 'danger')
        return redirect(url_for('dashboard'))

    # STRICT DATA ACCESS RESTRICTION FOR INDIVIDUAL ISSUE:
    role = session.get('role')
    user_id = session.get('user_id')
    user_dept = session.get('department')

    # Students & Faculty can ONLY view issues they raised
    if role in ['student', 'faculty'] and issue['reported_by_id'] != user_id:
        flash('Access Denied: You are only permitted to view issues reported by yourself.', 'danger')
        return redirect(url_for('dashboard'))

    # Staff can ONLY view issues assigned to their department
    if role == 'staff' and issue['assigned_department'] != user_dept:
        flash(f'Access Denied: You can only view issues assigned to {user_dept}.', 'danger')
        return redirect(url_for('dashboard'))

    # All departments for admin reassignment
    all_depts = ['Electrical Maintenance', 'Civil & Facilities', 'Plumbing Maintenance', 'IT Support', 'Admin Review']
    return render_template('issue_detail.html', issue=issue, all_depts=all_depts)

@app.route('/issue/<int:issue_id>/update-status', methods=['POST'])
@login_required
def update_status(issue_id):
    role = session.get('role')
    user_dept = session.get('department')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM issues WHERE id = ?', (issue_id,))
    issue = cursor.fetchone()

    if not issue:
        conn.close()
        flash('Issue not found.', 'danger')
        return redirect(url_for('dashboard'))

    # Permission check: Only Admin, or Staff belonging to assigned department, can change status
    if role != 'admin' and (role != 'staff' or issue['assigned_department'] != user_dept):
        conn.close()
        flash('Unauthorized: Only assigned department staff or administrators can update this issue status.', 'danger')
        return redirect(url_for('issue_detail', issue_id=issue_id))

    new_status = request.form.get('status')
    notes = request.form.get('resolution_notes', '').strip()

    if new_status in ['Open', 'In Progress', 'Resolved']:
        cursor.execute('''
            UPDATE issues
            SET status = ?, resolution_notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_status, notes if notes else issue['resolution_notes'], issue_id))
        conn.commit()
        flash(f'Issue #{issue_id} status updated to "{new_status}".', 'success')
    else:
        flash('Invalid status provided.', 'danger')

    conn.close()
    return redirect(url_for('issue_detail', issue_id=issue_id))

@app.route('/issue/<int:issue_id>/reassign', methods=['POST'])
@role_required(['admin'])
def reassign_department(issue_id):
    new_department = request.form.get('assigned_department', '').strip()
    if not new_department:
        flash('Department cannot be empty.', 'danger')
        return redirect(url_for('issue_detail', issue_id=issue_id))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE issues
        SET assigned_department = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (new_department, issue_id))
    conn.commit()
    conn.close()

    flash(f'Issue #{issue_id} reassigned to {new_department}.', 'success')
    return redirect(url_for('issue_detail', issue_id=issue_id))

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
