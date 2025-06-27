# TSMGMT/auth/models.py
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, email, name=None, picture=None):
        # Flask-Login uses `self.id` (string) as the unique identifier
        self.id = email
        self.name = name
        self.picture = picture
