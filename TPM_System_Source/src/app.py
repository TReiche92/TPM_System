from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response
from datetime import datetime, timedelta
import sqlite3
import os
import traceback
import sys
import hashlib
import csv
import io
import json
import logging
import webbrowser
import threading
import time
import secrets
import pystray
from PIL import Image

# Configure logging FIRST
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tpm_error.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Determine paths BEFORE creating Flask app
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    application_path = sys._MEIPASS
    database_path = os.path.join(os.path.dirname(sys.executable), 'tpm_database.db')
    template_folder = os.path.join(application_path, 'templates')
    static_folder = os.path.join(application_path, 'static')
else:
    # Running as normal Python script
    application_path = os.path.dirname(os.path.abspath(__file__))
    database_path = 'tpm_database.db'
    template_folder = 'templates'
    static_folder = 'static'

logger.info(f"Application path: {application_path}")
logger.info(f"Database path: {database_path}")
logger.info(f"Template folder: {template_folder}")

# Database connection function
def get_db():
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn

# Create Flask app with correct paths
app = Flask(__name__,
            template_folder=template_folder,
            static_folder=static_folder if os.path.exists(static_folder) else None)
app.secret_key = secrets.token_hex(16)
app.config['PROPAGATE_EXCEPTIONS'] = True

# Global variables for system tray
tray_icon = None
flask_thread = None
server_running = False
icon_path = os.path.join(application_path, 'OperationalExcellence.ico')

# Error handlers
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {error}")
    logger.error(traceback.format_exc())
    return "Internal Server Error - Check tpm_error.log for details", 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    logger.error(traceback.format_exc())
    return "An error occurred - Check tpm_error.log for details", 500


# Hardcoded shift definitions
SHIFT_DEFS = [
    ('A', '04:30', '15:30', 'Mon,Tue,Wed,Thu', 1),
    ('B', '16:30', '03:30', 'Mon,Tue,Wed,Thu', 2),
    ('C', '05:00', '17:00', 'Fri,Sat,Sun', 3),
    ('D', '17:00', '05:00', 'Fri,Sat,Sun', 4)
]

WEEK_IDX = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}

# Database initialization
def init_db():
    """Initialize the database with tables and default data"""
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                description TEXT,
                interval_days INTEGER DEFAULT 1,
                interval_type TEXT DEFAULT 'start_shift_daily',
                assigned_shift TEXT,
                category TEXT,
                priority TEXT DEFAULT 'medium',
                procedure_link TEXT,
                created_by TEXT,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Task assignments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                user_id INTEGER,
                assigned_date DATE,
                status TEXT DEFAULT 'pending',
                completed_at TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Shift configuration table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shift_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shift_name TEXT UNIQUE NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                active_days TEXT DEFAULT 'Mon,Tue,Wed,Thu,Fri,Sat,Sun',
                display_order INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            )
        ''')
        
        # Task completions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                completed_by TEXT NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        # Add missing columns to users table if they don't exist
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'password' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN password TEXT')
        if 'shift' not in columns:
            cursor.execute('ALTER TABLE users ADD COLUMN shift TEXT')
        
        # Check if admin user exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            # Create default admin user
            password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
            cursor.execute('''
                INSERT INTO users (username, password_hash, full_name, role)
                VALUES (?, ?, ?, ?)
            ''', ('admin', password_hash, 'Administrator', 'admin'))
            logger.info("Created default admin user")
        
        # Check if shift configs exist
        cursor.execute("SELECT COUNT(*) FROM shift_config")
        if cursor.fetchone()[0] == 0:
            # Create default shifts
            default_shifts = [
                ('A', '04:30', '15:30', 'Mon,Tue,Wed,Thu', 1),
                ('B', '16:30', '03:30', 'Mon,Tue,Wed,Thu', 2),
                ('C', '05:00', '17:00', 'Fri,Sat,Sun', 3),
                ('D', '17:00', '05:00', 'Fri,Sat,Sun', 4)
            ]
            cursor.executemany('''
                INSERT INTO shift_config (shift_name, start_time, end_time, active_days, display_order)
                VALUES (?, ?, ?, ?, ?)
            ''', default_shifts)
            logger.info("Created default shift configurations")
        
        # Check if template tasks exist
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE active = 1")
        if cursor.fetchone()[0] == 0:
            # Create default template tasks
            template_tasks = [
                ('Daily Equipment Inspection', 'Perform visual inspection of all production equipment', 1, 'start_shift_daily', 'A', 'Safety', 'high', '', 'system'),
                ('Weekly Lubrication Check', 'Check and refill lubrication points on machinery', 7, 'start_shift_weekly', 'A', 'Maintenance', 'medium', '', 'system'),
                ('End of Shift Cleanup', 'Clean work area and secure equipment', 1, 'end_shift_daily', '', 'Housekeeping', 'medium', '', 'system'),
                ('Monthly Calibration Verification', 'Verify calibration of measuring instruments', 30, 'start_shift_weekly', '', 'Quality', 'high', '', 'system'),
                ('Safety Meeting Attendance', 'Attend weekly safety briefing', 7, 'start_shift_weekly', '', 'Safety', 'high', '', 'system'),
                ('Production Log Review', 'Review and sign off on production logs', 1, 'end_shift_daily', '', 'Documentation', 'medium', '', 'system'),
                ('Emergency Equipment Check', 'Test emergency stop buttons and safety systems', 7, 'start_shift_weekly', '', 'Safety', 'high', '', 'system'),
                ('Tool Inventory Count', 'Count and verify tool inventory', 30, 'start_shift_weekly', '', 'Inventory', 'low', '', 'system')
            ]
            
            cursor.executemany('''
                INSERT INTO tasks (task_name, description, interval_days, interval_type,
                                 assigned_shift, category, priority, procedure_link, created_by, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', template_tasks)
            logger.info("Created default template tasks")
        
        conn.commit()
        conn.close()
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        logger.error(traceback.format_exc())
        raise


def get_db():
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_shifts_from_db():
    """Helper function to get active shifts from database"""
    conn = get_db()
    shifts = conn.execute('''
        SELECT shift_name, start_time, end_time, active_days 
        FROM shift_config 
        WHERE active = 1 
        ORDER BY display_order
    ''').fetchall()
    conn.close()
    
    shift_list = [s['shift_name'] for s in shifts]
    shift_times = {s['shift_name']: s['start_time'] for s in shifts}
    shift_days = {s['shift_name']: s['active_days'].split(',') for s in shifts}
    
    return shift_list, shift_times, shift_days

# NEW INTERVAL CALCULATION LOGIC
def calculate_next_due(last_completed, interval_days, interval_type, assigned_shift=None):
    """Calculate the next due date based on new interval types"""
    now = datetime.now()
    
    # If task was completed, calculate from completion time; otherwise from now
    reference_time = now
    if last_completed:
        try:
            reference_time = datetime.strptime(str(last_completed), '%Y-%m-%d %H:%M:%S')
        except:
            try:
                reference_time = datetime.strptime(str(last_completed), '%Y-%m-%d %H:%M')
            except:
                reference_time = now
    
    # Get shift configuration if assigned
    shift_row = None
    if assigned_shift:
        conn = get_db()
        shift_row = conn.execute(
            'SELECT * FROM shift_config WHERE shift_name = ? AND active = 1',
            (assigned_shift,)
        ).fetchone()
        conn.close()
    
    if shift_row:
        shift_days = [WEEK_IDX[d] for d in shift_row['active_days'].split(',')]
        first_day = min(shift_days)
        last_day = max(shift_days)
        start_time = datetime.strptime(shift_row['start_time'], '%H:%M').time()
        end_time = datetime.strptime(shift_row['end_time'], '%H:%M').time()
    else:
        shift_days = list(range(7))
        first_day, last_day = 0, 6
        start_time = end_time = datetime.strptime('00:00', '%H:%M').time()
    
    ref_day_idx = reference_time.weekday()
    
    # START OF SHIFT DAILY
    if interval_type == 'start_shift_daily':
        # Find the next shift day after reference time
        for i in range(1, 8):  # Start from 1 to skip today if already completed
            d_idx = (ref_day_idx + i) % 7
            if d_idx in shift_days:
                candidate = (reference_time + timedelta(days=i)).replace(
                    hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0
                )
                # Make sure it's after reference time
                if candidate > reference_time:
                    return candidate
        
        # Fallback to next week's first shift day
        days_until_first = (first_day - ref_day_idx) % 7
        if days_until_first == 0:
            days_until_first = 7
        return (reference_time + timedelta(days=days_until_first)).replace(
            hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0
        )
    
    # START OF SHIFT WEEKLY
    if interval_type == 'start_shift_weekly':
        # Calculate days until next first shift day
        days_until_first = (first_day - ref_day_idx) % 7
        
        # If we're on the first day but past the shift start time, or if days_until is 0, go to next week
        candidate = (reference_time + timedelta(days=days_until_first)).replace(
            hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0
        )
        
        if candidate <= reference_time:
            # Add a week
            candidate = candidate + timedelta(days=7)
        
        return candidate
    
    # END OF SHIFT DAILY
    if interval_type == 'end_shift_daily':
        # Find the next shift day after reference time
        for i in range(1, 8):
            d_idx = (ref_day_idx + i) % 7
            if d_idx in shift_days:
                candidate = (reference_time + timedelta(days=i)).replace(
                    hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0
                )
                if candidate > reference_time:
                    return candidate
        
        # Fallback
        days_until_first = (shift_days[0] - ref_day_idx) % 7
        if days_until_first == 0:
            days_until_first = 7
        return (reference_time + timedelta(days=days_until_first)).replace(
            hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0
        )
    
    # END OF SHIFT WEEKLY
    if interval_type == 'end_shift_weekly':
        # Calculate days until last shift day
        days_until_last = (last_day - ref_day_idx) % 7
        
        candidate = (reference_time + timedelta(days=days_until_last)).replace(
            hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0
        )
        
        if candidate <= reference_time:
            # Add a week
            candidate = candidate + timedelta(days=7)
        
        return candidate
    
    # Legacy interval types (fallback for any old data)
    if last_completed:
        try:
            last_completed_dt = datetime.strptime(str(last_completed), '%Y-%m-%d %H:%M:%S')
        except:
            try:
                last_completed_dt = datetime.strptime(str(last_completed), '%Y-%m-%d %H:%M')
            except:
                last_completed_dt = now
        return last_completed_dt + timedelta(days=interval_days or 1)
    else:
        return now


def get_task_status(next_due, last_completed=None, interval_type=None, assigned_shift=None):
    """Determine if task is overdue, due, completed, or upcoming"""
    now = datetime.now()
    
    # If we have completion info, check if task was completed in current shift period
    if last_completed and interval_type and assigned_shift:
        try:
            last_completed_dt = datetime.strptime(str(last_completed), '%Y-%m-%d %H:%M:%S')
        except:
            try:
                last_completed_dt = datetime.strptime(str(last_completed), '%Y-%m-%d %H:%M')
            except:
                last_completed_dt = None
        
        if last_completed_dt:
            # Check if task was completed within current shift period
            if is_completed_in_current_shift_period(last_completed_dt, interval_type, assigned_shift):
                return "completed"
    
    # Standard status logic
    if now > next_due:
        return "overdue"
    elif (next_due - now).days < 1:
        return "due"
    else:
        return "upcoming"

def is_completed_in_current_shift_period(completion_time, interval_type, assigned_shift):
    """Check if a task was completed within the current shift period"""
    now = datetime.now()
    
    # Get shift configuration
    shift_row = None
    if assigned_shift:
        conn = get_db()
        shift_row = conn.execute(
            'SELECT * FROM shift_config WHERE shift_name = ? AND active = 1',
            (assigned_shift,)
        ).fetchone()
        conn.close()
    
    if not shift_row:
        # If no shift config, use simple daily logic
        return completion_time.date() == now.date()
    
    shift_days = [WEEK_IDX[d] for d in shift_row['active_days'].split(',')]
    start_time = datetime.strptime(shift_row['start_time'], '%H:%M').time()
    end_time = datetime.strptime(shift_row['end_time'], '%H:%M').time()
    
    # For daily intervals, check if completed within current shift day
    if 'daily' in interval_type:
        return is_same_shift_occurrence(completion_time, now, shift_days, start_time, end_time)
    
    # For weekly intervals, check if completed within current shift week
    elif 'weekly' in interval_type:
        return is_same_shift_week(completion_time, now, shift_days, start_time, end_time)
    
    return False

def is_same_shift_occurrence(completion_time, current_time, shift_days, start_time, end_time):
    """Check if completion and current time are in the same shift occurrence"""
    
    def get_shift_date_for_time(dt):
        """Get the shift date for a given datetime"""
        day_idx = dt.weekday()
        
        # If not a shift day, return None
        if day_idx not in shift_days:
            return None
            
        # For overnight shifts, the shift "date" is the start date
        if end_time < start_time:  # Overnight shift
            if dt.time() >= start_time:
                # After start time, shift date is current date
                return dt.date()
            else:
                # Before end time, shift date is previous date
                return (dt - timedelta(days=1)).date()
        else:  # Same-day shift
            if start_time <= dt.time() < end_time:
                return dt.date()
            else:
                return None
    
    completion_shift_date = get_shift_date_for_time(completion_time)
    current_shift_date = get_shift_date_for_time(current_time)
    
    return (completion_shift_date is not None and
            current_shift_date is not None and
            completion_shift_date == current_shift_date)

def is_same_shift_week(completion_time, current_time, shift_days, start_time, end_time):
    """Check if completion and current time are in the same shift week"""
    
    def get_shift_week_start(dt):
        """Get the start date of the shift week for a given datetime"""
        first_shift_day = min(shift_days)
        
        # Find the most recent occurrence of the first shift day
        days_since_first = (dt.weekday() - first_shift_day) % 7
        week_start = dt - timedelta(days=days_since_first)
        
        # For overnight shifts starting on the first day, adjust if needed
        if (dt.weekday() == first_shift_day and
            end_time < start_time and
            dt.time() < start_time):
            week_start = week_start - timedelta(days=7)
            
        return week_start.date()
    
    completion_week_start = get_shift_week_start(completion_time)
    current_week_start = get_shift_week_start(current_time)
    
    return completion_week_start == current_week_start

# Authentication decorator
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def admin_required(f):
    def wrapper(*args, **kwargs):
        if 'username' not in session or session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# Routes
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Error: {error}")
    import traceback
    logger.error(traceback.format_exc())
    return "Internal Server Error - Check tpm_error.log for details", 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    import traceback
    logger.error(traceback.format_exc())
    return "An error occurred - Check tpm_error.log for details", 500

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = get_db()
        # Use COLLATE NOCASE for case-insensitive username comparison
        user = conn.execute('''
            SELECT * FROM users
            WHERE username = ? COLLATE NOCASE AND password_hash = ?
        ''', (username, password_hash)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']  # Store actual username from DB (preserves case)
            session['role'] = user['role']
            session['shift'] = user['shift']
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    shifts, _, _ = get_shifts_from_db()
    return render_template('dashboard.html', 
                         username=session['username'],
                         role=session['role'],
                         shift=session.get('shift'),
                         shifts=shifts)

@app.route('/api/config/shifts', methods=['GET'])
@login_required
def get_shift_config():
    """Get shift configuration"""
    shifts, shift_times, shift_days = get_shifts_from_db()
    return jsonify({
        'shifts': shifts,
        'shift_times': shift_times,
        'shift_days': shift_days
    })

# Task API Routes - UPDATED TO INCLUDE DESCRIPTION AND LAST COMPLETED INFO
@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    try:
        my_shift_only = request.args.get('my_shift_only', 'false').lower() == 'true'
        user_shift = session.get('shift')
        
        conn = get_db()
        
        # Updated query to get last_completed_by
        if my_shift_only and user_shift:
            tasks = conn.execute('''
                SELECT t.*, 
                       MAX(tc.completed_at) as last_completed,
                       (SELECT completed_by FROM task_completions 
                        WHERE task_id = t.id 
                        ORDER BY completed_at DESC LIMIT 1) as last_completed_by,
                       COUNT(tc.id) as completion_count
                FROM tasks t
                LEFT JOIN task_completions tc ON t.id = tc.task_id
                WHERE t.active = 1 AND (t.assigned_shift = ? OR t.assigned_shift IS NULL OR t.assigned_shift = '')
                GROUP BY t.id
                ORDER BY t.priority DESC, t.task_name
            ''', (user_shift,)).fetchall()
        else:
            tasks = conn.execute('''
                SELECT t.*, 
                       MAX(tc.completed_at) as last_completed,
                       (SELECT completed_by FROM task_completions 
                        WHERE task_id = t.id 
                        ORDER BY completed_at DESC LIMIT 1) as last_completed_by,
                       COUNT(tc.id) as completion_count
                FROM tasks t
                LEFT JOIN task_completions tc ON t.id = tc.task_id
                WHERE t.active = 1
                GROUP BY t.id
                ORDER BY t.priority DESC, t.task_name
            ''').fetchall()
        
        task_list = []
        for task in tasks:
            try:
                task_dict = dict(task)
                
                next_due = calculate_next_due(
                    task_dict.get('last_completed'),
                    task_dict.get('interval_days', 1),
                    task_dict.get('interval_type', 'start_shift_daily'),
                    task_dict.get('assigned_shift')
                )
                
                # FIX: Explicitly set the field names the frontend expects
                task_dict['last_completed_at'] = task_dict.get('last_completed')
                task_dict['next_due'] = next_due.strftime('%Y-%m-%d %H:%M')
                task_dict['status'] = get_task_status(
                    next_due,
                    task_dict.get('last_completed'),
                    task_dict.get('interval_type', 'start_shift_daily'),
                    task_dict.get('assigned_shift')
                )
                task_dict['days_until_due'] = (next_due - datetime.now()).days
                task_dict['hours_until_due'] = int((next_due - datetime.now()).total_seconds() / 3600)
                
                task_list.append(task_dict)
            except Exception as task_error:
                print(f"ERROR processing task {task_dict.get('id', 'unknown')}: {str(task_error)}")
                traceback.print_exc()
                continue
        
        conn.close()
        return jsonify(task_list)
        
    except Exception as e:
        print(f"ERROR in get_tasks: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to load tasks: {str(e)}'}), 500


@app.route('/api/tasks', methods=['POST'])
@login_required
@admin_required
def create_task():
    try:
        data = request.json
        
        if not data.get('task_name'):
            return jsonify({'error': 'Task name is required'}), 400
        
        if not data.get('interval_type'):
            return jsonify({'error': 'Interval type is required'}), 400
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO tasks (task_name, description, interval_days, interval_type, 
                              assigned_shift, category, priority, 
                              procedure_link, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['task_name'],
            data.get('description', ''),
            int(data.get('interval_days', 1)),
            data['interval_type'],
            data.get('assigned_shift', ''),
            data.get('category', ''),
            data.get('priority', 'medium'),
            data.get('procedure_link', ''),
            session['username']
        ))
        
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        
        print(f"Task created successfully with ID: {task_id}")
        return jsonify({'id': task_id, 'message': 'Task created successfully'}), 201
        
    except Exception as e:
        print(f"ERROR creating task: {str(e)}")
        return jsonify({'error': f'Failed to create task: {str(e)}'}), 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
@admin_required
def update_task(task_id):
    try:
        data = request.json
        
        conn = get_db()
        conn.execute('''
            UPDATE tasks 
            SET task_name = ?, description = ?, interval_days = ?, interval_type = ?,
                assigned_shift = ?, category = ?, priority = ?, 
                procedure_link = ?
            WHERE id = ?
        ''', (
            data['task_name'],
            data.get('description', ''),
            int(data.get('interval_days', 1)),
            data['interval_type'],
            data.get('assigned_shift', ''),
            data.get('category', ''),
            data.get('priority', 'medium'),
            data.get('procedure_link', ''),
            task_id
        ))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Task updated successfully'})
        
    except Exception as e:
        print(f"ERROR updating task: {str(e)}")
        return jsonify({'error': f'Failed to update task: {str(e)}'}), 500

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_task(task_id):
    conn = get_db()
    conn.execute('UPDATE tasks SET active = 0 WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Task deleted successfully'})

@app.route('/api/tasks/<int:task_id>/complete', methods=['POST'])
@login_required
def complete_task(task_id):
    data = request.json if request.is_json else {}
    notes = data.get('notes', '')
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO task_completions (task_id, completed_by, notes)
        VALUES (?, ?, ?)
    ''', (task_id, session['username'], notes))
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Task completed successfully'}), 201

# NEW ENDPOINT: Mark task as incomplete
@app.route('/api/tasks/<int:task_id>/incomplete', methods=['POST'])
@login_required
def mark_task_incomplete(task_id):
    """Remove the most recent completion for a task"""
    try:
        conn = get_db()
        # Delete the most recent completion
        conn.execute('''
            DELETE FROM task_completions 
            WHERE id = (
                SELECT id FROM task_completions 
                WHERE task_id = ? 
                ORDER BY completed_at DESC 
                LIMIT 1
            )
        ''', (task_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Task marked as incomplete'}), 200
        
    except Exception as e:
        print(f"ERROR marking task incomplete: {str(e)}")
        return jsonify({'error': f'Failed to mark task as incomplete: {str(e)}'}), 500

# User Management API Routes
@app.route('/api/users', methods=['GET'])
@login_required
@login_required
def get_users():
    conn = get_db()
    users = conn.execute('SELECT id, username, role, shift, created_at FROM users ORDER BY username').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/users', methods=['POST'])
@login_required
@admin_required
def create_user():
    try:
        data = request.json
        
        if not data.get('username'):
            return jsonify({'error': 'Username is required'}), 400
        
        if not data.get('password'):
            return jsonify({'error': 'Password is required'}), 400
        
        if not data.get('role') or data['role'] not in ['admin', 'operator']:
            return jsonify({'error': 'Valid role is required (admin or operator)'}), 400
        
        password_hash = hashlib.sha256(data['password'].encode()).hexdigest()
        shift = None if data['role'] == 'admin' else data.get('shift')
        
        conn = get_db()
        c = conn.cursor()
        
        try:
            c.execute('''
                INSERT INTO users (username, password, role, shift)
                VALUES (?, ?, ?, ?)
            ''', (data['username'], password_hash, data['role'], shift))
            
            user_id = c.lastrowid
            conn.commit()
            conn.close()
            
            print(f"User created: {data['username']} ({data['role']}) - Shift: {shift}")
            return jsonify({'id': user_id, 'message': 'User created successfully'}), 201
            
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'error': 'Username already exists'}), 409
        
    except Exception as e:
        print(f"ERROR creating user: {str(e)}")
        return jsonify({'error': f'Failed to create user: {str(e)}'}), 500

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def update_user(user_id):
    try:
        data = request.json
        
        if user_id == session.get('user_id') and data.get('role') != 'admin':
            return jsonify({'error': 'You cannot change your own admin role'}), 403
        
        shift = None if data['role'] == 'admin' else data.get('shift')
        
        conn = get_db()
        c = conn.cursor()
        
        if data.get('password'):
            password_hash = hashlib.sha256(data['password'].encode()).hexdigest()
            c.execute('''
                UPDATE users 
                SET username = ?, password = ?, role = ?, shift = ?
                WHERE id = ?
            ''', (data['username'], password_hash, data['role'], shift, user_id))
        else:
            c.execute('''
                UPDATE users 
                SET username = ?, role = ?, shift = ?
                WHERE id = ?
            ''', (data['username'], data['role'], shift, user_id))
        
        conn.commit()
        conn.close()
        
        print(f"User updated: {data['username']}")
        return jsonify({'message': 'User updated successfully'})
        
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 409
    except Exception as e:
        print(f"ERROR updating user: {str(e)}")
        return jsonify({'error': f'Failed to update user: {str(e)}'}), 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    try:
        conn = get_db()
        current_user = conn.execute('SELECT id FROM users WHERE username = ?', 
                                    (session['username'],)).fetchone()
        
        if current_user and current_user['id'] == user_id:
            conn.close()
            return jsonify({'error': 'You cannot delete your own account'}), 403
        
        user = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        print(f"User deleted: {user['username']}")
        return jsonify({'message': 'User deleted successfully'})
        
    except Exception as e:
        print(f"ERROR deleting user: {str(e)}")
        return jsonify({'error': f'Failed to delete user: {str(e)}'}), 500

@app.route('/api/users/change-password', methods=['POST'])
@login_required
def change_own_password():
    try:
        data = request.json
        
        if not data.get('current_password') or not data.get('new_password'):
            return jsonify({'error': 'Current and new passwords are required'}), 400
        
        current_password_hash = hashlib.sha256(data['current_password'].encode()).hexdigest()
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?',
                          (session['username'], current_password_hash)).fetchone()
        
        if not user:
            conn.close()
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        new_password_hash = hashlib.sha256(data['new_password'].encode()).hexdigest()
        conn.execute('UPDATE users SET password = ? WHERE username = ?',
                    (new_password_hash, session['username']))
        conn.commit()
        conn.close()
        
        print(f"Password changed for user: {session['username']}")
        return jsonify({'message': 'Password changed successfully'})
        
    except Exception as e:
        print(f"ERROR changing password: {str(e)}")
        return jsonify({'error': f'Failed to change password: {str(e)}'}), 500

# Shift Configuration Management
@app.route('/api/shifts', methods=['GET'])
@login_required
def get_shifts():
    conn = get_db()
    shifts = conn.execute('''
        SELECT * FROM shift_config 
        ORDER BY display_order
    ''').fetchall()
    conn.close()
    return jsonify([dict(s) for s in shifts])

@app.route('/api/shifts', methods=['POST'])
@login_required
@admin_required
def create_shift():
    return jsonify({'error': 'Shifts are hardcoded and cannot be modified'}), 403

@app.route('/api/shifts/<int:shift_id>', methods=['PUT'])
@login_required
@admin_required
def update_shift(shift_id):
    return jsonify({'error': 'Shifts are hardcoded and cannot be modified'}), 403

@app.route('/api/shifts/<int:shift_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_shift(shift_id):
    return jsonify({'error': 'Shifts are hardcoded and cannot be deleted'}), 403
    
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'running',
        'service': 'TPM System',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': '2.0'
    }), 200

@app.route('/api/ignition/active-shift', methods=['GET'])
def get_active_shift():
    """Get the currently active shift"""
    try:
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        current_minutes = current_hour * 60 + current_minute
        current_day = now.strftime('%a')
        
        conn = get_db()
        shifts = conn.execute('''
            SELECT shift_name, start_time, end_time, active_days
            FROM shift_config
            WHERE active = 1
            ORDER BY display_order
        ''').fetchall()
        conn.close()
        
        if not shifts:
            return jsonify({
                'status': 'success',
                'shift': 'A',
                'note': 'No shifts configured',
                'timestamp': now.isoformat()
            })
        
        active_shift = None
        
        for shift in shifts:
            # Check if current day is in shift's active days
            if current_day not in shift['active_days'].split(','):
                continue
            
            try:
                start_parts = shift['start_time'].split(':')
                start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
                
                end_parts = shift['end_time'].split(':')
                end_minutes = int(end_parts[0]) * 60 + int(end_parts[1])
            except:
                continue
            
            # Check if current time is in this shift
            if end_minutes > start_minutes:
                # Same-day shift
                if start_minutes <= current_minutes < end_minutes:
                    active_shift = shift['shift_name']
                    break
            else:
                # Overnight shift
                if current_minutes >= start_minutes or current_minutes < end_minutes:
                    active_shift = shift['shift_name']
                    break
        
        if active_shift:
            return jsonify({
                'status': 'success',
                'shift': active_shift,
                'timestamp': now.isoformat(),
                'current_time': f'{current_hour:02d}:{current_minute:02d}'
            })
        else:
            return jsonify({
                'status': 'success',
                'shift': 'A',
                'timestamp': now.isoformat(),
                'current_time': f'{current_hour:02d}:{current_minute:02d}',
                'note': 'No shift matched current time'
            })
    
    except Exception as e:
        print("ERROR in active-shift endpoint:")
        print(str(e))
        traceback.print_exc(file=sys.stdout)
        
        return jsonify({
            'status': 'error',
            'shift': 'A',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 200

# NEW ENDPOINT: Run Permissive for Ignition
@app.route('/api/ignition/run_permissive', methods=['GET'])
def ignition_run_permissive():
    """Check if all high priority tasks are completed for the shift"""
    try:
        shift = request.args.get('shift', 'A')
        
        conn = get_db()
        # Get all high priority tasks for this shift
        tasks = conn.execute('''
            SELECT t.*, MAX(tc.completed_at) as last_completed 
            FROM tasks t
            LEFT JOIN task_completions tc ON t.id = tc.task_id
            WHERE t.active = 1 
            AND t.priority = 'high'
            AND (t.assigned_shift = ? OR t.assigned_shift IS NULL OR t.assigned_shift = '')
            GROUP BY t.id
        ''', (shift,)).fetchall()
        conn.close()
        
        # Check if any high priority task is overdue
        for task in tasks:
            next_due = calculate_next_due(
                task['last_completed'],
                task['interval_days'],
                task['interval_type'],
                task['assigned_shift']
            )
            
            if get_task_status(next_due, task['last_completed'], task['interval_type'], task['assigned_shift']) == 'overdue':
                return jsonify({
                    'run_permissive': False,
                    'reason': f'High priority task "{task["task_name"]}" is overdue'
                })
        
        return jsonify({'run_permissive': True})
        
    except Exception as e:
        print(f"ERROR in run_permissive: {str(e)}")
        traceback.print_exc()
        return jsonify({'run_permissive': False, 'error': str(e)}), 500

# Reports API
@app.route('/api/tasks/<int:task_id>/history', methods=['GET'])
@login_required
def get_task_history(task_id):
    conn = get_db()
    history = conn.execute('''
        SELECT tc.*, t.task_name
        FROM task_completions tc
        JOIN tasks t ON tc.task_id = t.id
        WHERE tc.task_id = ?
        ORDER BY tc.completed_at DESC
        LIMIT 50
    ''', (task_id,)).fetchall()
    
    conn.close()
    return jsonify([dict(h) for h in history])

@app.route('/api/reports/summary', methods=['GET'])
@login_required
def get_summary_report():
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
    user_filter = request.args.get('user', '')
    
    try:
        conn = get_db()
        
        # Get completion statistics with optional user filter
        query = '''
            SELECT 
                t.task_name,
                t.category,
                t.assigned_shift,
                COUNT(tc.id) as completion_count,
                tc.completed_by
            FROM task_completions tc
            JOIN tasks t ON tc.task_id = t.id
            WHERE tc.completed_at BETWEEN ? AND ?
        '''
        params = [start_date + ' 00:00:00', end_date + ' 23:59:59']
        
        if user_filter:
            query += ' AND tc.completed_by = ?'
            params.append(user_filter)
        
        query += ' GROUP BY t.id, tc.completed_by'
        
        completions = conn.execute(query, params).fetchall()
        
        # Get overdue tasks
        overdue = conn.execute('''
            SELECT t.*, MAX(tc.completed_at) as last_completed
            FROM tasks t
            LEFT JOIN task_completions tc ON t.id = tc.task_id
            WHERE t.active = 1
            GROUP BY t.id
        ''').fetchall()
        
        overdue_list = []
        for task in overdue:
            try:
                task_dict = dict(task)
                
                next_due = calculate_next_due(
                    task_dict.get('last_completed'),
                    task_dict.get('interval_days', 1),
                    task_dict.get('interval_type', 'start_shift_daily'),
                    task_dict.get('assigned_shift')
                )
                
                if next_due < datetime.now():
                    hours_overdue = int((datetime.now() - next_due).total_seconds() / 3600)
                    overdue_list.append({
                        'task_name': task_dict.get('task_name', 'Unknown'),
                        'hours_overdue': hours_overdue,
                        'days_overdue': hours_overdue // 24,
                        'last_completed': task_dict.get('last_completed') or 'Never',
                        'procedure_link': task_dict.get('procedure_link', ''),
                        'assigned_shift': task_dict.get('assigned_shift') or 'All'
                    })
            except Exception as task_error:
                print(f"ERROR processing overdue task: {str(task_error)}")
                traceback.print_exc()
                continue
        
        # Get completion trend
        trend_query = '''
            SELECT DATE(completed_at) as date, COUNT(*) as count
            FROM task_completions
            WHERE completed_at BETWEEN ? AND ?
        '''
        trend_params = [start_date + ' 00:00:00', end_date + ' 23:59:59']
        
        if user_filter:
            trend_query += ' AND completed_by = ?'
            trend_params.append(user_filter)
        
        trend_query += ' GROUP BY DATE(completed_at) ORDER BY date'
        
        completion_trend = conn.execute(trend_query, trend_params).fetchall()
        
        conn.close()
        
        return jsonify({
            'completions': [dict(c) for c in completions],
            'overdue_tasks': overdue_list,
            'completion_trend': [dict(ct) for ct in completion_trend],
            'date_range': {'start': start_date, 'end': end_date},
            'user_filter': user_filter
        })
        
    except Exception as e:
        print(f"ERROR in get_summary_report: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to generate report: {str(e)}'}), 500

# NEW ENDPOINT: CSV Export
@app.route('/api/reports/export', methods=['GET'])
@login_required
def export_report_csv():
    """Export task completions to CSV with optional filters"""
    start_date = request.args.get('start', '')
    end_date = request.args.get('end', '')
    user_filter = request.args.get('user', '')
    
    try:
        conn = get_db()
        
        query = '''
            SELECT tc.*, t.task_name, t.category, t.assigned_shift
            FROM task_completions tc
            JOIN tasks t ON tc.task_id = t.id
            WHERE 1=1
        '''
        params = []
        
        if start_date:
            query += ' AND tc.completed_at >= ?'
            params.append(start_date + ' 00:00:00')
        
        if end_date:
            query += ' AND tc.completed_at <= ?'
            params.append(end_date + ' 23:59:59')
        
        if user_filter:
            query += ' AND tc.completed_by = ?'
            params.append(user_filter)
        
        query += ' ORDER BY tc.completed_at DESC'
        
        rows = conn.execute(query, params).fetchall()
        conn.close()
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['Task Name', 'Category', 'Shift', 'Completed By', 'Completed At', 'Notes'])
        
        # Write data
        for row in rows:
            writer.writerow([
                row['task_name'],
                row['category'] or '',
                row['assigned_shift'] or 'All',
                row['completed_by'],
                row['completed_at'],
                row['notes'] or ''
            ])
        
        output.seek(0)
        
        # Generate filename based on user filter
        if user_filter:
            # Remove any special characters from username for filename
            safe_username = ''.join(c for c in user_filter if c.isalnum() or c in ('_', '-'))
            filename = f"TPM_Report_{safe_username}.csv"
        else:
            filename = "TPM_Report_AllUsers.csv"
        
        return Response(
            output,
            mimetype='text/csv',
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        print(f"ERROR in export_report_csv: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to export CSV: {str(e)}'}), 500

# Import/Export API endpoints
@app.route('/api/admin/export', methods=['GET'])
@login_required
@admin_required
def export_system_data():
    """Export tasks and users data for system migration"""
    try:
        conn = get_db()
        
        # Export tasks (excluding completions for clean migration)
        tasks = conn.execute('''
            SELECT task_name, description, interval_days, interval_type,
                   assigned_shift, category, priority, procedure_link, active
            FROM tasks
            WHERE created_by != 'system' OR created_by IS NULL
            ORDER BY task_name
        ''').fetchall()
        
        # Export users (excluding admin to prevent conflicts)
        users = conn.execute('''
            SELECT username, role, shift
            FROM users
            WHERE username != 'admin'
            ORDER BY username
        ''').fetchall()
        
        # Export shift configurations (if customized)
        shifts = conn.execute('''
            SELECT shift_name, start_time, end_time, active_days, display_order, active
            FROM shift_config
            ORDER BY display_order
        ''').fetchall()
        
        conn.close()
        
        # Create export data structure
        export_data = {
            'export_info': {
                'timestamp': datetime.now().isoformat(),
                'version': '2.0',
                'exported_by': session['username']
            },
            'tasks': [dict(task) for task in tasks],
            'users': [dict(user) for user in users],
            'shifts': [dict(shift) for shift in shifts]
        }
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"TPM_System_Export_{timestamp}.json"
        
        return Response(
            json.dumps(export_data, indent=2),
            mimetype='application/json',
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )
        
    except Exception as e:
        logger.error(f"ERROR in export_system_data: {str(e)}")
        return jsonify({'error': f'Failed to export system data: {str(e)}'}), 500

@app.route('/api/admin/import', methods=['POST'])
@login_required
@admin_required
def import_system_data():
    """Import tasks and users data from another TPM system"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.json'):
            return jsonify({'error': 'File must be a JSON file'}), 400
        
        # Read and parse JSON data
        try:
            import_data = json.loads(file.read().decode('utf-8'))
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON file: {str(e)}'}), 400
        
        # Validate import data structure
        required_keys = ['export_info', 'tasks', 'users']
        if not all(key in import_data for key in required_keys):
            return jsonify({'error': 'Invalid export file format'}), 400
        
        conn = get_db()
        c = conn.cursor()
        
        imported_counts = {'tasks': 0, 'users': 0, 'shifts': 0}
        
        # Import tasks
        for task_data in import_data.get('tasks', []):
            try:
                c.execute('''
                    INSERT OR REPLACE INTO tasks
                    (task_name, description, interval_days, interval_type,
                     assigned_shift, category, priority, procedure_link, active, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task_data.get('task_name'),
                    task_data.get('description', ''),
                    task_data.get('interval_days', 1),
                    task_data.get('interval_type', 'start_shift_daily'),
                    task_data.get('assigned_shift', ''),
                    task_data.get('category', ''),
                    task_data.get('priority', 'medium'),
                    task_data.get('procedure_link', ''),
                    task_data.get('active', 1),
                    f"imported_by_{session['username']}"
                ))
                imported_counts['tasks'] += 1
            except Exception as task_error:
                logger.warning(f"Failed to import task {task_data.get('task_name', 'unknown')}: {str(task_error)}")
        
        # Import users (with password reset required)
        default_password_hash = hashlib.sha256('changeme123'.encode()).hexdigest()
        for user_data in import_data.get('users', []):
            try:
                # Skip if username already exists
                existing = c.execute('SELECT id FROM users WHERE username = ?',
                                   (user_data.get('username'),)).fetchone()
                if existing:
                    continue
                    
                c.execute('''
                    INSERT INTO users (username, password, role, shift)
                    VALUES (?, ?, ?, ?)
                ''', (
                    user_data.get('username'),
                    default_password_hash,  # Default password: changeme123
                    user_data.get('role', 'operator'),
                    user_data.get('shift', '')
                ))
                imported_counts['users'] += 1
            except Exception as user_error:
                logger.warning(f"Failed to import user {user_data.get('username', 'unknown')}: {str(user_error)}")
        
        # Import shifts (optional, only if provided)
        for shift_data in import_data.get('shifts', []):
            try:
                c.execute('''
                    INSERT OR REPLACE INTO shift_config
                    (shift_name, start_time, end_time, active_days, display_order, active)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    shift_data.get('shift_name'),
                    shift_data.get('start_time'),
                    shift_data.get('end_time'),
                    shift_data.get('active_days', ''),
                    shift_data.get('display_order', 0),
                    shift_data.get('active', 1)
                ))
                imported_counts['shifts'] += 1
            except Exception as shift_error:
                logger.warning(f"Failed to import shift {shift_data.get('shift_name', 'unknown')}: {str(shift_error)}")
        
        conn.commit()
        conn.close()
        
        logger.info(f"Import completed by {session['username']}: {imported_counts}")
        
        return jsonify({
            'message': 'Import completed successfully',
            'imported': imported_counts,
            'note': 'Imported users have default password: changeme123'
        }), 200
        
    except Exception as e:
        logger.error(f"ERROR in import_system_data: {str(e)}")
        return jsonify({'error': f'Failed to import system data: {str(e)}'}), 500


# Ignition Edge API endpoints
@app.route('/api/ignition/tasks', methods=['GET'])
def ignition_get_tasks():
    try:
        api_key = request.headers.get('X-API-Key')
        shift_filter = request.args.get('shift')
        
        conn = get_db()
        
        if shift_filter:
            tasks = conn.execute('''
                SELECT t.*, 
                       MAX(tc.completed_at) as last_completed,
                       (SELECT completed_by FROM task_completions 
                        WHERE task_id = t.id 
                        ORDER BY completed_at DESC LIMIT 1) as last_completed_by
                FROM tasks t
                LEFT JOIN task_completions tc ON t.id = tc.task_id
                WHERE t.active = 1 AND (t.assigned_shift = ? OR t.assigned_shift IS NULL OR t.assigned_shift = '')
                GROUP BY t.id
            ''', (shift_filter,)).fetchall()
        else:
            tasks = conn.execute('''
                SELECT t.*, 
                       MAX(tc.completed_at) as last_completed,
                       (SELECT completed_by FROM task_completions 
                        WHERE task_id = t.id 
                        ORDER BY completed_at DESC LIMIT 1) as last_completed_by
                FROM tasks t
                LEFT JOIN task_completions tc ON t.id = tc.task_id
                WHERE t.active = 1
                GROUP BY t.id
            ''').fetchall()
        
        task_list = []
        for task in tasks:
            try:
                task_dict = dict(task)
                
                next_due = calculate_next_due(
                    task_dict.get('last_completed'),
                    task_dict.get('interval_days', 1),
                    task_dict.get('interval_type', 'start_shift_daily'),
                    task_dict.get('assigned_shift')
                )
                
                task_dict['next_due'] = next_due.strftime('%Y-%m-%d %H:%M')
                task_dict['status'] = get_task_status(
                    next_due,
                    task_dict.get('last_completed'),
                    task_dict.get('interval_type', 'start_shift_daily'),
                    task_dict.get('assigned_shift')
                )
                task_dict['hours_until_due'] = int((next_due - datetime.now()).total_seconds() / 3600)
                
                task_list.append(task_dict)
            except Exception as task_error:
                print(f"ERROR processing task: {str(task_error)}")
                traceback.print_exc()
                continue
        
        conn.close()
        return jsonify(task_list)
        
    except Exception as e:
        print(f"ERROR in ignition_get_tasks: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to load tasks: {str(e)}'}), 500

@app.route('/api/ignition/tasks/<int:task_id>/complete', methods=['POST'])
def ignition_complete_task(task_id):
    api_key = request.headers.get('X-API-Key')
    data = request.json if request.is_json else {}
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO task_completions (task_id, completed_by, notes)
        VALUES (?, ?, ?)
    ''', (task_id, data.get('completed_by', 'Ignition'), data.get('notes', '')))
    
    conn.commit()
    conn.close()
    
    return jsonify({'message': 'Task completed successfully'}), 201

@app.route('/api/ignition/tasks/<int:task_id>', methods=['GET'])
def ignition_get_task_details(task_id):
    api_key = request.headers.get('X-API-Key')
    
    conn = get_db()
    task = conn.execute('SELECT * FROM tasks WHERE id = ? AND active = 1', (task_id,)).fetchone()
    
    if not task:
        conn.close()
        return jsonify({'error': 'Task not found'}), 404
    
    history = conn.execute('''
        SELECT * FROM task_completions 
        WHERE task_id = ? 
        ORDER BY completed_at DESC 
        LIMIT 10
    ''', (task_id,)).fetchall()
    
    conn.close()
    
    task_dict = dict(task)
    task_dict['completion_history'] = [dict(h) for h in history]
    
    return jsonify(task_dict)

def open_browser():
    """Open the default browser after a short delay to ensure server is ready"""
    time.sleep(2)  # Wait 2 seconds for server to start
    try:
        webbrowser.open('http://localhost:8080')
        logger.info("Opened browser automatically")
    except Exception as e:
        logger.warning(f"Could not open browser automatically: {e}")

def start_flask_server():
    """Start the Flask server in a separate thread"""
    global server_running
    try:
        # Initialize database
        init_db()
        
        # Use debug mode only in development (not when compiled as executable)
        debug_mode = not is_executable
        server_running = True
        
        logger.info("Starting Flask server...")
        app.run(debug=debug_mode, host='0.0.0.0', port=8080, use_reloader=False, threaded=True)
    except Exception as e:
        logger.error(f"Flask server error: {e}")
        server_running = False

def create_tray_icon():
    """Create system tray icon"""
    try:
        # Try to load the icon file
        if os.path.exists(icon_path):
            image = Image.open(icon_path)
        else:
            # Create a simple default icon if file not found
            image = Image.new('RGB', (64, 64), color='blue')
        
        # Create menu items
        menu = pystray.Menu(
            pystray.MenuItem("Open TPM System", open_tpm_system),
            pystray.MenuItem("Status", show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", quit_application)
        )
        
        # Create tray icon
        icon = pystray.Icon("TPM System", image, "TPM System - Running", menu)
        return icon
    except Exception as e:
        logger.error(f"Error creating tray icon: {e}")
        # Create minimal icon without image
        menu = pystray.Menu(
            pystray.MenuItem("Open TPM System", open_tpm_system),
            pystray.MenuItem("Exit", quit_application)
        )
        icon = pystray.Icon("TPM System", menu=menu)
        return icon

def open_tpm_system(icon=None, item=None):
    """Open TPM System in browser"""
    try:
        webbrowser.open('http://localhost:8080')
    except Exception as e:
        logger.error(f"Failed to open browser: {e}")

def show_status(icon=None, item=None):
    """Show application status"""
    status = "Running" if server_running else "Stopped"
    logger.info(f"TPM System Status: {status}")

def quit_application(icon=None, item=None):
    """Quit the application"""
    global tray_icon, server_running
    logger.info("Shutting down TPM System...")
    server_running = False
    if tray_icon:
        tray_icon.stop()
    os._exit(0)

def main():
    """Main application entry point"""
    global tray_icon, flask_thread
    
    try:
        logger.info("Starting TPM System GUI...")
        
        # Start Flask server in background thread
        flask_thread = threading.Thread(target=start_flask_server, daemon=True)
        flask_thread.start()
        
        # Wait a moment for server to start
        time.sleep(3)
        
        # Open browser automatically
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()
        
        # Create and run system tray icon
        tray_icon = create_tray_icon()
        logger.info("TPM System running in system tray")
        tray_icon.run()  # This blocks until the icon is stopped
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Determine if running as executable or development
    is_executable = getattr(sys, 'frozen', False)
    
    if is_executable:
        # Running as GUI executable - use system tray
        main()
    else:
        # Running as development script - use console mode
        init_db()
        print("\n" + "="*70)
        print("  TPM SYSTEM - STARTING")
        print("="*70)
        print("\n  * Running on PORT 8080")
        print("\n  * Opening browser automatically...")
        print("\n  * Access the application at:")
        print("     - http://localhost:8080")
        print("     - http://127.0.0.1:8080")
        print("\n  * Default Credentials:")
        print("     Admin:    admin / admin123")
        print("     Operator: operator / operator123 (Shift A)")
        print("\n  * Hardcoded Shifts:")
        print("     A: 04:30-15:30 Mon-Thu")
        print("     B: 16:30-03:30 Mon-Thu")
        print("     C: 05:00-17:00 Fri-Sun")
        print("     D: 17:00-05:00 Fri-Sun")
        print("\n  * Interval Types:")
        print("     - Start of shift daily")
        print("     - Start of shift weekly")
        print("     - End of shift daily")
        print("     - End of shift weekly")
        print("\n  * Ignition API:")
        print("     - http://localhost:8080/api/ignition/tasks")
        print("     - http://localhost:8080/api/ignition/run_permissive")
        print("     - Add ?shift=A to filter by shift")
        print("\n" + "="*70 + "\n")
        
        # Only start browser opening thread if not in debug mode
        if not app.debug:
            browser_thread = threading.Thread(target=open_browser, daemon=True)
            browser_thread.start()
        
        # Use debug mode only in development
        debug_mode = True
        
        app.run(debug=debug_mode, host='0.0.0.0', port=8080, use_reloader=debug_mode)
