from flask import Flask, redirect, request, session
from msal import ConfidentialClientApplication
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Replace with your Azure AD app details
CLIENT_ID = 'your-client-id'  # Application (client) ID
CLIENT_SECRET = 'your-client-secret'  # Client secret
TENANT_ID = 'your-tenant-id'  # Directory (tenant) ID
AUTHORITY = f'https://login.microsoftonline.com/{TENANT_ID}'
REDIRECT_URI = 'http://localhost:5000/callback'  # Redirect URI

# Initialize MSAL confidential client
msal_app = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET,
)

@app.route('/')
def index():
    return 'Welcome to the OIDC Authentication Example! <a href="/login">Login</a>'

@app.route('/login')
def login():
    auth_url = msal_app.get_authorization_request_url(
        scopes=['openid', 'profile', 'User.Read'],  # Required scopes
        redirect_uri=REDIRECT_URI,
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    # Get the authorization code from the query parameters
    code = request.args.get('code')
    # Exchange the authorization code for tokens
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=['openid', 'profile', 'User.Read'],
        redirect_uri=REDIRECT_URI,
    )
    
    if 'access_token' in result:
        print('Authentication successful!')
        return 'You have been authenticated! You can close this window.'
    else:
        return 'Login failed: ' + str(result.get('error'))

if __name__ == '__main__':
    app.run(debug=True)
