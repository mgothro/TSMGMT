# TSMGMT/main/routes.py
from flask import Blueprint, render_template, session, redirect, url_for
from datetime import datetime

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    user = session.get('user')
    if not user:
        return redirect(url_for('auth.login'))

    tools = [
        {
            'name': 'Todo Status Tracker',
            'description': 'View and update your Basecamp todos',
            'endpoint': 'work_status.index'
        },
        {
            'name': 'Admin View Todo Status Tracker',
            'description': "View Team's Todos",
            'endpoint': 'work_status.admin_view'
        },
        {   'name': 'Site Group Explorer',
            'description': 'View sitegroup details',
            'endpoint': 'sitegroup.index'
        },

        #{
        #    'name': 'Another Tool',
        #    'description': 'Description for your next tool',
        #    'endpoint': 'your_tool_bp.index'
        #},
        #add more tools here
    ]

    return render_template(
        'main/home.html',
        user=user,
        tools=tools,
        year=datetime.utcnow().year
    )

@main_bp.route('/about')
def about():
    return render_template('main/about.html')

@main_bp.route('/contact')
def contact():
    return render_template('main/contact.html')

