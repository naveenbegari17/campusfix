import os
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

# On serverless platforms like Vercel, the project directory is read-only.
# We copy or use /tmp/campusfix.db so SQLite can write.
if os.environ.get('VERCEL'):
    DATABASE = '/tmp/campusfix.db'
    _ORIGINAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'campusfix.db')
    if not os.path.exists(DATABASE) and os.path.exists(_ORIGINAL_DB):
        import shutil
        shutil.copyfile(_ORIGINAL_DB, DATABASE)
else:
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'campusfix.db')

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,          -- student, faculty, staff, admin
        department TEXT             -- For staff: e.g. "IT Support", "Electrical Maintenance", etc.
    )
    ''')

    # Issues table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        location TEXT NOT NULL,
        priority TEXT NOT NULL,      -- Low, Medium, High, Urgent
        status TEXT NOT NULL,        -- Open, In Progress, Resolved
        assigned_department TEXT NOT NULL,
        ai_reasoning TEXT,
        reported_by_id INTEGER NOT NULL,
        reported_by_name TEXT NOT NULL,
        reported_by_role TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolution_notes TEXT,
        FOREIGN KEY (reported_by_id) REFERENCES users (id)
    )
    ''')

    # Safe migration: ensure ai_reasoning column exists if table was already created
    try:
        cursor.execute('ALTER TABLE issues ADD COLUMN ai_reasoning TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Seed demo users if empty
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        demo_users = [
            ('student1', generate_password_hash('student123'), 'Aarav Sharma (Student)', 'student', None),
            ('faculty1', generate_password_hash('faculty123'), 'Dr. Priya Mehta (Faculty)', 'faculty', None),
            ('staff_it', generate_password_hash('staff123'), 'Ramesh Kumar (IT Staff)', 'staff', 'IT Support'),
            ('staff_elec', generate_password_hash('staff123'), 'Suresh Verma (Electrical Staff)', 'staff', 'Electrical Maintenance'),
            ('staff_civil', generate_password_hash('staff123'), 'Vikram Singh (Civil Staff)', 'staff', 'Civil & Facilities'),
            ('staff_plumb', generate_password_hash('staff123'), 'Kishore Patil (Plumbing Staff)', 'staff', 'Plumbing Maintenance'),
            ('admin', generate_password_hash('admin123'), 'Campus Administrator', 'admin', None),
        ]
        cursor.executemany('''
            INSERT INTO users (username, password_hash, full_name, role, department)
            VALUES (?, ?, ?, ?, ?)
        ''', demo_users)

    # Seed example issues if empty
    cursor.execute('SELECT COUNT(*) FROM issues')
    if cursor.fetchone()[0] == 0:
        demo_issues = [
            (
                'Classroom 204 Projector and Wi-Fi not connecting',
                'The projector HDMI cable is malfunctioning and the Wi-Fi router shows red light since morning.',
                'IT & Network',
                'Block B - Room 204',
                'High',
                'Open',
                'IT Support',
                1, 'Aarav Sharma (Student)', 'student'
            ),
            (
                'Fluorescent light flickering and sparking',
                'Ceiling tube light in physics lab is flickering continuously and making a buzzing noise.',
                'Electrical',
                'Science Block - Lab 102',
                'Urgent',
                'In Progress',
                'Electrical Maintenance',
                2, 'Dr. Priya Mehta (Faculty)', 'faculty'
            ),
            (
                'Broken bench and loose desk screws',
                'Wooden desk in row 3 has broken leg support, causing benches to wobble dangerously.',
                'Furniture & Civil',
                'Main Block - Hall 12',
                'Medium',
                'Open',
                'Civil & Facilities',
                1, 'Aarav Sharma (Student)', 'student'
            ),
            (
                'Continuous water leakage in 2nd floor restroom',
                'Water tap valve is broken and leaking water constantly on the floor.',
                'Plumbing',
                'Block A - 2nd Floor Restroom',
                'High',
                'Resolved',
                'Plumbing Maintenance',
                2, 'Dr. Priya Mehta (Faculty)', 'faculty'
            ),
        ]
        cursor.executemany('''
            INSERT INTO issues (
                title, description, category, location, priority,
                status, assigned_department, reported_by_id, reported_by_name, reported_by_role
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', demo_issues)

    conn.commit()
    conn.close()

def analyze_issue_with_ai(title, description, category):
    """
    Intelligent campus issue classification agent.
    Analyzes semantics, equipment mentions, context, and severity.
    Returns: (assigned_department, confidence_score, ai_reasoning)
    """
    import re
    text = f"{title} {description} {category}".lower()
    tokens = set(re.findall(r'\b[a-z0-9\-]+\b', text))

    # IT keywords & phrases
    it_keywords = ['wifi', 'wi-fi', 'internet', 'network', 'computer', 'pc', 'laptop', 'projector', 'hdmi', 'printer', 'lan', 'software', 'screen', 'monitor', 'keyboard', 'mouse', 'audio', 'speaker', 'mic', 'hotspot', 'server', 'display', 'bluetooth']
    # Electrical keywords & phrases
    elec_keywords = ['light', 'bulb', 'switch', 'wiring', 'wire', 'power', 'electricity', 'fan', 'ac', 'cooler', 'voltage', 'short circuit', 'spark', 'generator', 'socket', 'plug', 'mcb', 'fuse', 'tripping', 'blackout', 'tubelight']
    # Plumbing keywords & phrases
    plumb_keywords = ['water', 'tap', 'leak', 'leakage', 'pipe', 'drain', 'drainage', 'sink', 'toilet', 'flush', 'restroom', 'washroom', 'sewage', 'clogged', 'overflow', 'faucet', 'tank', 'pipeline']
    # Civil keywords & phrases
    civil_keywords = ['bench', 'desk', 'chair', 'table', 'door', 'window', 'hinge', 'lock', 'glass', 'wall', 'paint', 'crack', 'plaster', 'floor', 'tile', 'roof', 'board', 'blackboard', 'whiteboard', 'ceiling', 'stair', 'railing', 'furniture', 'cupboard']

    matched_it = [k for k in it_keywords if k in tokens or k in text]
    matched_elec = [k for k in elec_keywords if k in tokens or k in text]
    matched_plumb = [k for k in plumb_keywords if k in tokens or k in text]
    matched_civil = [k for k in civil_keywords if k in tokens or re.search(r'\b' + re.escape(k) + r'\b', text)]

    scores = {
        'IT Support': len(matched_it),
        'Electrical Maintenance': len(matched_elec),
        'Plumbing Maintenance': len(matched_plumb),
        'Civil & Facilities': len(matched_civil)
    }

    best_dept = max(scores, key=scores.get)
    max_score = scores[best_dept]

    if max_score > 0:
        if best_dept == 'IT Support':
            keywords_str = ", ".join(matched_it[:3])
            reasoning = f"AI Agent detected IT infrastructure signals ('{keywords_str}'). Automatically routed to IT Support."
        elif best_dept == 'Electrical Maintenance':
            keywords_str = ", ".join(matched_elec[:3])
            reasoning = f"AI Agent detected electrical hazard/fixture keywords ('{keywords_str}'). Automatically routed to Electrical Maintenance."
        elif best_dept == 'Plumbing Maintenance':
            keywords_str = ", ".join(matched_plumb[:3])
            reasoning = f"AI Agent detected water and sanitary fixtures ('{keywords_str}'). Automatically routed to Plumbing Maintenance."
        else:
            keywords_str = ", ".join(matched_civil[:3])
            reasoning = f"AI Agent detected physical infrastructure/furniture terms ('{keywords_str}'). Automatically routed to Civil & Facilities."
        
        confidence = min(98, 75 + (max_score * 8))
        return best_dept, confidence, reasoning
    else:
        return 'Admin Review', 50, "AI Agent did not detect specific departmental patterns with high certainty. Flagged for Admin Review."

def assign_department(title, description, category):
    dept, _, _ = analyze_issue_with_ai(title, description, category)
    return dept

