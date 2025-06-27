# TSMGMT/auth/routes.py
from flask import Blueprint, redirect, url_for, session, current_app
from authlib.integrations.flask_client import OAuth
from authlib.common.security import generate_token
from .models import User
from flask_login import login_user

auth_bp = Blueprint('auth', __name__)
oauth = OAuth()

@auth_bp.record
def init_oauth(state):
    app = state.app
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

@auth_bp.route('/login')
def login():
    # generate a random nonce and save to session
    nonce = generate_token(48)
    session['nonce'] = nonce

    redirect_uri = url_for('auth.auth_callback', _external=True)
    # pass the nonce in the authorize_redirect call
    return oauth.google.authorize_redirect(redirect_uri, nonce=nonce)

@auth_bp.route('/auth_callback')
def auth_callback():
    # fetch the token
    token = oauth.google.authorize_access_token()

    # retrieve our nonce from the session
    nonce = session.pop('nonce', None)
    if nonce is None:
        # no nonce: something went wrong
        return "Missing nonce, please try logging in again.", 400

    # now parse the ID token with the nonce
    user_info = oauth.google.parse_id_token(token, nonce=nonce)

    # 1) keep the user info in session
    session['user'] = {
        'email':   user_info['email'],
        'name':    user_info.get('name'),
        'picture': user_info.get('picture'),
    }
    user = User(**session['user'])

    login_user(user)

    return redirect(url_for('main.home'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.home'))
