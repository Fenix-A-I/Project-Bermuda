from flask import Flask, redirect, request, url_for
from authlib.integrations.flask_client import OAuth
import os

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Set your Azure AD credentials
CLIENT_ID =  
CLIENT_SECRET = 
TENANT_ID = 
AUTHORITY =
REDIRECT_URI = 'http://localhost:8000/callback'

# Set up the OAuth client
oauth = OAuth(app)
azure = oauth.register(
    name='azure',
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    authorize_url=f'{AUTHORITY}/oauth2/v2.0/authorize',
    authorize_params=None,
    access_token_url=f'{AUTHORITY}/oauth2/v2.0/token',
    access_token_params=None,
    client_kwargs={'scope': 'openid profile email User.Read'},
    redirect_uri=REDIRECT_URI,
)

# Route to initiate authentication
@app.route('/')
def index():
    return '<a href="/login">Log in with Azure AD</a>'

# Route for login
@app.route('/login')
def login():
    return azure.authorize_redirect(redirect_uri=REDIRECT_URI)

# Callback route
@app.route('/callback')
def callback():
    token = azure.authorize_access_token()  # Fetch the token using the authorization code
    user_info = azure.get('https://graph.microsoft.com/v1.0/me').json()  # Use token to get user info
    return f"Hello, {user_info['displayName']}! Your email is {user_info.get('mail') or user_info.get('userPrincipalName')}."

# Run the Flask app
if __name__ == '__main__':
    app.run(port=5000)
