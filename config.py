# config.py
import os

APP_SECRET_KEY       = os.getenv('TSMGMT_APP_SECRET_KEY')
GOOGLE_CLIENT_ID     = os.getenv('TSMGMT_GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET	 = os.getenv('TSMGMT_GOOGLE_CLIENT_SECRET')

# Basecamp OAuth credentials:
BASECAMP_CLIENT_ID     = os.getenv('TSMGMT_BASECAMP_CLIENT_ID')
BASECAMP_CLIENT_SECRET = os.getenv('TSMGMT_BASECAMP_CLIENT_SECRET')
BASECAMP_ACCOUNT_ID    = os.getenv('TSMGMT_BASECAMP_ACCOUNT_ID')

if not APP_SECRET_KEY or not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("Missing required environment variables: TSMGMT_APP_SECRET_KEY, TSMGMT_GOOGLE_CLIENT_ID, TSMGMT_GOOGLE_CLIENT_SECRET")

DBCONN_PROD_SERVER = os.getenv('TSMGMT_DBCONN_PROD_SERVER')
DBCONN_BOMS_SERVER = os.getenv('TSMGMT_DBCONN_BOMS_SERVER')

DATABASE_CONFIG = {
    'SMS': {
        'server': DBCONN_PROD_SERVER,
        'database': 'SMS'
    },
    'GMS': {
        'server': DBCONN_PROD_SERVER,
        'database': 'GMS'
    },
    'BOMS': {
        'server': DBCONN_BOMS_SERVER + '\\bomslive',
        'database': 'BOMS'
    }
}