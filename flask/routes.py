#!/usr/bin/env python3
import argparse
from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room
import flask
import pty
import os
import subprocess
import select
import termios
import uuid
import struct
import fcntl
import shlex
import logging
import sys
import socket
import json
import flask_login
from flask_login import current_user
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import msal
import requests
from authlib.integrations.flask_client import OAuth
from sqlalchemy.orm import DeclarativeBase
from db import *
from utils import *
from podman import PodmanClient


logging.getLogger("werkzeug").setLevel(logging.ERROR)

__version__ = "0.5.0.2"

app = Flask(
    __name__,
    template_folder="./templates",
    static_folder="./templates",
    static_url_path="",
)

with open('credentials.json', 'r') as file:
    config = json.load(file)

app.config["SECRET_KEY"] = config['FLASK_SECRET']
app.config["podman_uri"] = "unix:///run/user/1000/podman/podman.sock"
socketio = SocketIO(app)
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
login_manager.login_view = "/landing"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///project.db"
db.init_app(app)

# Set your Azure AD credentials
CLIENT_ID = config['CLIENT_ID']
CLIENT_SECRET =  config['CLIENT_SECRET'] 
TENANT_ID = config['TENANT_ID'] 
AUTHORITY = f'https://login.microsoftonline.com/{TENANT_ID}'
SCOPES = ['User.Read']
REDIRECT_URI = 'http://localhost:5000/callback'



# MSAL ConfidentialClientApplication
app_msal = msal.ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET,  # Pass CLIENT_SECRET directly as a string
)

oauth = OAuth(app)
azure = oauth.register(
    name='azure',
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    authorize_url=f'{AUTHORITY}/oauth2/v2.0/authorize',
    access_token_url=f'{AUTHORITY}/oauth2/v2.0/token',
    client_kwargs={'scope': 'openid profile email User.Read'},
    redirect_uri=REDIRECT_URI,
)

with app.app_context():
    db.create_all()


@login_manager.user_loader
def user_loader(email):
    return User.query.filter_by(email=email).first()

@app.route('/authenticate')
def login():
    # Redirect to Azure AD authorization endpoint
    return azure.authorize_redirect(redirect_uri=REDIRECT_URI)


@app.route('/callback')
def callback():
    # Get the authorization code from the query parameters
    code = request.args.get('code')
    if not code:
        return "Authorization failed: No authorization code provided."

    # Exchange the authorization code for tokens using MSAL
    result = app_msal.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    if "access_token" in result:
        access_token = result["access_token"]

        # Fetch user information
        user_info_response = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        if user_info_response.status_code == 200:
            user_info = user_info_response.json()
            email = user_info.get('mail') or user_info.get('userPrincipalName')

            # Check if the user's email ends with @uoregon.edu
            if email and email.endswith('@uoregon.edu'):
                user = User.query.filter_by(email=email).first()
                if user is None:
                    user = User(email=email, container_name=str(uuid.uuid4()))
                    db.session.add(user)
                    db.session.commit()
                flask_login.login_user(user)
                return flask.redirect(flask.url_for("index"))

            else:
                return "Authentication successful, but only @uoregon.edu accounts are allowed."

        else:
            return f"Failed to fetch user info: {user_info_response.status_code}, {user_info_response.text}"

    return f"Failed to acquire token: {result.get('error_description')}"

@app.route("/")
@flask_login.login_required
def index():
    return render_template("ssh_entry.html")


@app.route("/logout")
@flask_login.login_required
def logout():
    flask_login.logout_user()
    return "Logged Out"


@app.route("/whoami")
@flask_login.login_required
def whoami():
    return str(current_user.get_id())


@app.route("/landing")
def landing():
    return render_template("landing.html")


@app.route("/terminal")
# @flask_login.login_required
def terminal():
    return render_template("terminal.html")


def set_winsize(fd, row, col, xpix=0, ypix=0):
    logging.debug("setting window size with termios")
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def read_and_forward_pty_output(user_id):
    with app.app_context():
        max_read_bytes = 1024 * 20
        while True:
            try:
                user = User.query.get(user_id)
                print(f"thread for {user.email}")
                terminal_session = Terminal_Session.query.filter_by(
                    user_id=user_id
                ).first()
                if terminal_session == None:
                    return
                alive_child = check_pid(terminal_session.pid)
                open_fd = is_fd_open(terminal_session.fd)

                # Something happened to the session, bailing
                if not (alive_child and open_fd):
                    return

                socketio.sleep(0.01)
                if terminal_session.fd:
                    timeout_sec = 10
                    (data_ready, _, _) = select.select(
                        [terminal_session.fd], [], [], timeout_sec
                    )
                    if data_ready:
                        output = os.read(terminal_session.fd, max_read_bytes).decode(
                            errors="ignore"
                        )
                        socketio.emit(
                            "pty-output",
                            {"output": output},
                            namespace="/pty",
                            room=user.email,
                        )
                else:
                    return
            except OSError:
                logging.info("Terminal closed, deleting session")
                db.session.delete(terminal_session)
                db.session.commit()


@socketio.on("pty-input", namespace="/pty")
def pty_input(data):
    """write to the child pty. The pty sees this as if you are typing in a real
    terminal.
    """
    if not current_user.is_authenticated:
        print("rejected unauthenticated user")
        return
    user_id = current_user.get_db_id()
    terminal_session = Terminal_Session.query.filter_by(user_id=user_id).first()
    if terminal_session == None:
        return
    if terminal_session.fd:
        logging.debug("received input from browser: %s" % data["input"])
        os.write(terminal_session.fd, data["input"].encode())


@socketio.on("resize", namespace="/pty")
def resize(data):
    if not current_user.is_authenticated:
        print("rejected unauthenticated user")
        return

    user_id = current_user.get_db_id()
    terminal_session = Terminal_Session.query.filter_by(user_id=user_id).first()
    if terminal_session == None:
        return

    if terminal_session.fd:
        logging.debug(f"Resizing window to {data['rows']}x{data['cols']}")
        set_winsize(terminal_session.fd, data["rows"], data["cols"])


@socketio.on("connect", namespace="/pty")
def connect(auth):
    """new client connected"""
    if not current_user.is_authenticated:
        print("rejected unauthenticated user")
        return

    logging.info("new client connected")
    join_room(current_user.email)

    user_id = current_user.get_db_id()
    terminal_session = Terminal_Session.query.filter_by(user_id=user_id).first()
    if terminal_session != None:
        alive_child = check_pid(terminal_session.pid)
        open_fd = is_fd_open(terminal_session.fd)
        new_session_needed = False

        if alive_child:
            os.kill(terminal_session.pid, 15)
            new_session_needed = True

        if open_fd:
            os.close(terminal_session.fd)
            new_session_needed = True

        if new_session_needed:
            subprocess.run(
                ["/usr/bin/podman", "rm", "--force", current_user.container_name]
            )
            db.session.delete(terminal_session)
            db.session.commit()
            terminal_session = Terminal_Session(user_id=user_id)
    else:
        terminal_session = Terminal_Session(user_id=user_id)

    process = subprocess.Popen(
        [
            "/usr/bin/podman",
            "ps",
            "--filter",
            f"name={current_user.container_name}",
            "--format",
            "{{.Names}}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate()

    print("stdot", stdout)
    (child_pid, fd) = pty.fork()
    if child_pid == 0:
        # this is the child process fork.
        # anything printed here will show up in the pty, including the output
        # of this subprocess
        if stdout.strip():  # If the output is not empty, container exists
            print("You already have a terminal session open!")
            return
        else:
            subprocess.run(
                [
                    "/usr/bin/podman",
                    "run",
                    "--rm",
                    "-it",
                    "--replace",
                    "--name",
                    current_user.container_name,
                    "localhost/kali-image:latest",
                ]
            )
            return
    else:
        # this is the parent process fork.
        # store child fd and pid
        terminal_session.fd = fd
        terminal_session.pid = child_pid
        db.session.add(terminal_session)
        db.session.commit()
        set_winsize(fd, 50, 50)
        # logging/print statements must go after this because... I have no idea why
        # but if they come before the background task never starts
        socketio.start_background_task(
            target=read_and_forward_pty_output, user_id=user_id
        )

        logging.info("child pid is " + str(child_pid))
        logging.info("task started")


def main():
    socketio.run(app, debug=True, port=5000, host="0.0.0.0")


if __name__ == "__main__":
    main()
