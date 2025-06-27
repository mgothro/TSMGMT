# TSMGMT/work_status/routes.py
from itertools import cycle
from flask import Blueprint, render_template, session, redirect, url_for, request, current_app, flash, Response, stream_with_context
from flask_login import login_required
from .basecamp import connect_basecamp, basecamp_callback, get_user_todos, sync_basecamp_cache_with_yield, get_all_todos
from ..db.connection import execute_query, execute_many
from datetime import date, datetime, time
from ..utils import to_pst
import os

work_status_bp = Blueprint('work_status', __name__, url_prefix='/work_status')

@work_status_bp.route('/')
def index():
    user = session.get('user')
    if not user:
        return redirect(url_for('auth.login'))
    # Prompt connection if no Basecamp token
    if 'basecamp_token' not in session:
        return render_template('work_status/connect.html', user=user)
    # Fetch todos from Basecamp
    todos = get_user_todos(user)
    today = datetime.combine(date.today(), time.min)

    try:
        row = execute_query("SELECT sms.dbo.UtcToPacific(MAX(clicked_at)) AS last_refreshed FROM BasecampSyncLog ")

        last_refreshed = str(row[0]['last_refreshed'] if row and row[0]['last_refreshed'] else None)
    except Exception:
        current_app.logger.exception("Failed to load last_refreshed")
        last_refreshed = None

    #if date, make it readable (am/pm)
    if last_refreshed:
        last_refreshed = to_pst(last_refreshed)

    return render_template('work_status/index.html', todos=todos, user=user, today=today, last_refreshed=last_refreshed)

@work_status_bp.route('/admin_view')
def admin_view():
    # require admin
    user = session.get('user')
    admin_email = os.getenv("ADMIN_EMAIL", "matt@cityspan.com")

    if not user or user.get('email') != admin_email:
        flash("You must be an admin to view this page.", "danger")
        return redirect(url_for('work_status.index'))

    # fetch all todos (excluding matt)
    todos = get_all_todos()

    # explicit mapping of email -> bootstrap badge color
    email_colors = json.loads(os.environ.get('EMAIL_COLORS', '{}'))
    default_email_color = 'dark'

    # today at midnight for due-date comparisons
    today = datetime.combine(date.today(), time.min)

    return render_template(
        'work_status/admin_view.html',
        todos=todos,
        today=today,
        email_colors=email_colors,
        default_email_color=default_email_color
    )

@work_status_bp.route('/connect')
def connect():
    return connect_basecamp()

@work_status_bp.route('/basecamp_callback')
def callback():
    return basecamp_callback()

@work_status_bp.route('/basecamp_logout')
@login_required
def basecamp_logout():
    session.pop('basecamp_token', None)  # remove from session
    flash('Your Basecamp connection has been cleared.', 'info')
    return redirect(url_for('work_status.connect'))  # or a dashboard route


@login_required
@work_status_bp.route('/sync_stream')
def sync_stream():
    #log the sync time
    user = session.get('user') or {}
    user_email = user.get('email', 'unknown')

    try:
        execute_query(
            "INSERT INTO BasecampSyncLog (user_email, clicked_at) VALUES (?, ?)",
            params=(user_email, datetime.utcnow())
        )
    except Exception:
        current_app.logger.exception("Failed to log sync click")

    token = session.get('basecamp_token')
    def generate():
        # send an 8KB comment to force an initial flush
        yield b":" + (b" " * 8190) + b"\n\n"

        try:
            for msg in sync_basecamp_cache_with_yield(token):
                yield f"data: {msg}\n\n".encode("utf-8")
        except Exception as e:
            # emit a special ERROR event with the exception text
            err = str(e).replace("\n", " ")
            yield f"data: SYNC_ERROR:{err}\n\n".encode("utf-8")
            # make sure to close after the error
            return

    headers = {
        'Cache-Control': 'no-cache',
        'Connection':    'keep-alive'
    }
    resp = Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers=headers
    )
    resp.direct_passthrough = True
    return resp

@work_status_bp.route('/update', methods=['POST'])
@login_required
def update_status():
    # 1) Parse JSON
    data = request.get_json(silent=True)
    if not data or 'id' not in data or 'status' not in data:
        return {'error': 'id and status required'}, 400

    id   = data['id']
    status    = data['status']

    # 2) Get the current user�s email
    user = session.get('user')
    if not user or 'email' not in user:
        return {'error': 'not authenticated'}, 401
    user_email = user['email']
    
    updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 3) Upsert into BasecampTaskStatus (id, user_email, status)
    sql = """
    IF EXISTS (
      SELECT 1 FROM BasecampTaskStatus 
       WHERE id = ? AND user_email = ?
    )
      UPDATE BasecampTaskStatus
         SET status = ?, updated_at = ?
       WHERE id = ? AND user_email = ?;
    ELSE
      INSERT INTO BasecampTaskStatus (id, user_email, status, updated_at)
           VALUES (?, ?, ?, ?);
    """
    # Placeholder order:
    #  1: id, 2: user_email,            (EXISTS)
    #  3: status, 4: id, 5: user_email, (UPDATE)
    #  6: id, 7: user_email, 8: status  (INSERT)
    params = [
      (
        id, user_email,
        status, updated_at,  id,    user_email,
        id, user_email, status, updated_at
      )
    ]

    try:
        execute_many(sql, data=params)
    except Exception:
        current_app.logger.exception("Failed to update BasecampTaskStatus")
        return {'error': 'database error'}, 500

    # 4) 204 No Content so front-end knows it's done
    return ('', 204)

@work_status_bp.route('/reorder', methods=['POST'])
def reorder_todos():
    data = request.get_json(silent=True)
    positions = data.get('positions')
    if not positions or not isinstance(positions, list):
        return {'error': 'positions list required'}, 400

    user_email = session['user']['email']
    updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Prepare upserts: for each item, update status and position
    sql = """
    IF EXISTS (
      SELECT 1 FROM BasecampTaskStatus
       WHERE id = ? AND user_email = ?
    )
      UPDATE BasecampTaskStatus
         SET status = ?, position = ?, updated_at = ?
       WHERE id = ? AND user_email = ?;
    ELSE
      INSERT INTO BasecampTaskStatus(id, user_email, status, position, updated_at)
           VALUES (?, ?, ?, ?, ?);
    """
    params = []
    for item in positions:
        if not all(k in item for k in ('id', 'status', 'position')):
            continue 

        tid = item['id']
        st  = item['status']
        pos = item['position']
        params.append((tid, user_email, st, pos, updated_at, tid, user_email,   # update
                       tid, user_email, st, pos, updated_at))      # insert

    try:
        execute_many(sql, data=params)
    except Exception:
        current_app.logger.exception("Failed to reorder todos")
        return {'error': 'db error'}, 500

    return ('', 204)
