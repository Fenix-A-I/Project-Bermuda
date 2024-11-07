import requests
import time
import msal


CLIENT_ID = 
CLIENT_SECRET =  
TENANT_ID = 
AUTHORITY = 
SCOPES = 

# Create a MSAL Public Client Application
app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)

# Step 1: Request a device code
device_code_response = app.initiate_device_flow(scopes=SCOPES)

if 'user_code' not in device_code_response:
    raise Exception("Failed to create device flow. Error: " + device_code_response.get("error_description"))

print(f"To authenticate, please visit {device_code_response['verification_uri']} and enter the code: {device_code_response['user_code']}")

# Step 2: Poll for the token endpoint until authentication completes
print("Waiting for user to authenticate...")

while True:
    result = app.acquire_token_by_device_flow(device_code_response)  # This will check if the user completed authentication
    if "access_token" in result:
        print("Authentication successful!")
        access_token = result['access_token']
        break
    elif "error" in result and result['error'] != "authorization_pending":
        raise Exception("Error: " + result.get("error_description"))
    time.sleep(device_code_response['interval'])

# Step 3: Use the access token to fetch user information
user_info_response = requests.get(
    'https://graph.microsoft.com/v1.0/me',
    headers={'Authorization': f'Bearer {access_token}'}
)
user_info_response.raise_for_status()  # Check for HTTP errors

user_info = user_info_response.json()
# Check if the user's email ends with @uoregon.edu
email = user_info.get('mail') or user_info.get('userPrincipalName')
if email and email.endswith('@uoregon.edu'):
    print(f"Hello, {user_info['displayName']}! Your email is {email}.")
else:
    print("Authentication successful, but only @uoregon.edu accounts are allowed.")