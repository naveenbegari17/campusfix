import unittest
from app import app
from db import init_db, assign_department, get_db

class CampusFixTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        self.client = app.test_client()
        with app.app_context():
            init_db()

    def test_department_assignment_rules(self):
        # Electrical rule
        self.assertEqual(assign_department('Broken light switch', 'Sparking', 'Electrical'), 'Electrical Maintenance')
        # Civil rule
        self.assertEqual(assign_department('Broken desk and bench', 'wobbling', 'Furniture'), 'Civil & Facilities')
        # Plumbing rule
        self.assertEqual(assign_department('Water tap leakage', 'flooded sink', 'Plumbing'), 'Plumbing Maintenance')
        # IT rule
        self.assertEqual(assign_department('Wi-Fi connection drop', 'laptop cannot connect', 'IT'), 'IT Support')
        # Unknown fallback rule
        self.assertEqual(assign_department('Strange sound', 'near tree', 'Other'), 'Admin Review')

    def test_login_flow(self):
        # Student login
        res = self.client.post('/login', data={'username': 'student1', 'password': 'student123'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Aarav Sharma', res.data)

    def test_create_issue_and_auto_assignment(self):
        # Login as student
        self.client.post('/login', data={'username': 'student1', 'password': 'student123'})
        # Raise issue with wifi keyword
        res = self.client.post('/raise-issue', data={
            'title': 'Library wifi not working on 3rd floor',
            'description': 'Laptops cannot connect to library hotspot',
            'category': 'IT & Network',
            'location': 'Central Library 3rd Floor',
            'priority': 'High'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'IT Support', res.data)

    def test_unauthorized_status_update(self):
        # Student logs in and tries to update issue #1 (assigned to IT Support)
        self.client.post('/login', data={'username': 'student1', 'password': 'student123'})
        res = self.client.post('/issue/1/update-status', data={'status': 'Resolved'}, follow_redirects=True)
        self.assertIn(b'Unauthorized', res.data)

    def test_authorized_staff_status_update(self):
        # IT Staff logs in and updates issue #1 (assigned to IT Support)
        # Ensure issue #1 is IT Support
        conn = get_db()
        conn.execute("UPDATE issues SET assigned_department = 'IT Support' WHERE id = 1")
        conn.commit()
        conn.close()

        self.client.post('/login', data={'username': 'staff_it', 'password': 'staff123'})
        res = self.client.post('/issue/1/update-status', data={
            'status': 'Resolved',
            'resolution_notes': 'Replaced damaged cable and reset router.'
        }, follow_redirects=True)
        self.assertIn(b'status updated to', res.data)
        self.assertIn(b'Resolved', res.data)

    def test_admin_reassign_department(self):
        # Admin reassigns issue #1
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        res = self.client.post('/issue/1/reassign', data={
            'assigned_department': 'Civil & Facilities'
        }, follow_redirects=True)
        self.assertTrue(b'Civil &amp; Facilities' in res.data or b'Civil & Facilities' in res.data)

    def test_strict_student_access_isolation(self):
        # Student 1 logs in. Issue #2 was reported by Faculty (ID 2).
        # Student 1 must be blocked from viewing issue #2.
        self.client.post('/login', data={'username': 'student1', 'password': 'student123'})
        res = self.client.get('/issue/2', follow_redirects=True)
        self.assertIn(b'Access Denied', res.data)

    def test_strict_staff_department_isolation(self):
        # IT staff logs in. Issue #4 is Plumbing Maintenance.
        # IT staff must be blocked from viewing Plumbing issue.
        self.client.post('/login', data={'username': 'staff_it', 'password': 'staff123'})
        res = self.client.get('/issue/4', follow_redirects=True)
        self.assertIn(b'Access Denied', res.data)

    def test_admin_full_access(self):
        # Admin can view any issue
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        res = self.client.get('/issue/4', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Continuous water leakage', res.data)

    def test_delete_issue_permissions(self):
        # Student 1 raises an issue
        self.client.post('/login', data={'username': 'student1', 'password': 'student123'})
        self.client.post('/raise-issue', data={
            'title': 'Test temp issue to delete',
            'description': 'Temporary test issue',
            'category': 'General & Other',
            'location': 'Hall A',
            'priority': 'Low'
        })
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM issues WHERE title = 'Test temp issue to delete'")
        issue_row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(issue_row)
        new_id = issue_row['id']

        # Staff IT attempts to delete -> Must be rejected (Unauthorized)
        self.client.post('/login', data={'username': 'staff_it', 'password': 'staff123'})
        res = self.client.post(f'/issue/{new_id}/delete', follow_redirects=True)
        self.assertIn(b'Unauthorized', res.data)

        # Student 1 attempts to delete their own issue -> Must ALSO be rejected (Unauthorized)
        self.client.post('/login', data={'username': 'student1', 'password': 'student123'})
        res = self.client.post(f'/issue/{new_id}/delete', follow_redirects=True)
        self.assertIn(b'Unauthorized', res.data)

        # Admin deletes the issue -> Success
        self.client.post('/login', data={'username': 'admin', 'password': 'admin123'})
        res = self.client.post(f'/issue/{new_id}/delete', follow_redirects=True)
        self.assertIn(b'permanently deleted', res.data)

if __name__ == '__main__':
    unittest.main()
