from flask import Flask , request, url_for
from .auth.models import User
from .auth.routes import auth_bp
from .main.routes import main_bp
from .work_status.basecamp import init_basecamp_oauth
from .work_status.routes import work_status_bp
from .sitegroup.routes import sitegroup_bp
from flask_login import LoginManager
from flask import session

def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config.from_object('config')
    app.secret_key = app.config['APP_SECRET_KEY']
    init_basecamp_oauth(app)

    app.config.from_mapping(
    DEBUG=True,
    ENV='development',         # makes Flask enable the debugger
    PROPAGATE_EXCEPTIONS=True, # ensures the exception reaches WSGI
    )

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'   # endpoint name for your login page
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        # grab the user-info dict you stored in session during OAuth
        user_data = session.get("user")
        if user_data and user_data.get("email") == user_id:
            return User(
                email   = user_data["email"],
                name    = user_data.get("name"),
                picture = user_data.get("picture")
            )
        return None

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp) 
    app.register_blueprint(work_status_bp, url_prefix='/work_status')
    app.register_blueprint(sitegroup_bp, url_prefix='/sitegroup')

    #app.register_blueprint(work_status_bp, url_prefix='/work_status')
    # … register other blueprints

    @app.context_processor
    def inject_back_url():
        def back_url(default_endpoint='main.home', **kwargs):
            # 1) look for explicit ?next=
            nxt = request.args.get('next')
            if nxt:
                return nxt
            # 2) fall back to Referer header
            if request.referrer:
                return request.referrer
            # 3) fall back to a sane default
            return url_for(default_endpoint, **kwargs)
        return dict(back_url=back_url)

    return app
