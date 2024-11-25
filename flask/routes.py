#!/usr/bin/env python3
import argparse
from flask import Flask, render_template
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
import flask_login
from flask_login import current_user
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from db import *
from utils import *
from podman import PodmanClient


logging.getLogger("werkzeug").setLevel(logging.ERROR)

__version__ = "0.5.0.2"

app = Flask(
    __name__,
    template_folder="./templates",
    static_folder="./static",
    static_url_path="",
)
app.config["SECRET_KEY"] = "secret!"
app.config["podman_uri"] = "unix:///run/user/1000/podman/podman.sock"
socketio = SocketIO(app)
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
login_manager.login_view = "/landing"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///project.db"
db.init_app(app)

with app.app_context():
    db.create_all()


@login_manager.user_loader
def user_loader(email):
    return User.query.filter_by(email=email).first()


@app.route("/authenticate", methods=["GET", "POST"])
def authenticate():
    if flask.request.method == "GET":
        return """
               <form action='authenticate' method='POST'>
                <input type='text' name='email' id='email' placeholder='email'/>
                <input type='submit' name='submit'/>
               </form>
               """

    email = flask.request.form["email"]
    if email and email.endswith("@uoregon.edu"):
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(email=email, container_name=str(uuid.uuid4()))
            db.session.add(user)
            db.session.commit()
        flask_login.login_user(user)
        return flask.redirect(flask.url_for("terminal"))

    return "Bad login"


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
            user = User.query.get(user_id)
            print(f"thread for {user.email}")
            terminal_session = Terminal_Session.query.filter_by(user_id=user_id).first()
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

        if alive_child:
            os.kill(terminal_session.pid, 15)

        if open_fd:
            os.close(terminal_session.fd)
    else:
        terminal_session = Terminal_Session(user_id=user_id)

    with PodmanClient(base_url=app.config["podman_uri"]) as client:
        # find container for current user
        user_container = None
        containers = client.containers
        for container in containers.list(all=True):
            container.reload()
            if container.name == current_user.container_name:
                user_container = container

        user_image = None 
        for image in client.images.list():
            if image.tags == ['localhost/kali-image:latest']:
                user_image = image

        if user_container == None:
            user_container = containers.create(
                image=user_image,
                command=["/bin/bash"],
                init=True,
                mem_limit="300m",
                name=current_user.container_name,
                cap_add=["cap_net_raw"],
            )

        container_status = user_container.status

        (child_pid, fd) = pty.fork()
        if child_pid == 0:
            # this is the child process fork.
            # anything printed here will show up in the pty, including the output
            # of this subprocess
            if container_status != "running":
                subprocess.run(["/usr/bin/podman", "exec", "-it", current_user.container_name, "/bin/bash"])
            else:
                subprocess.run(["/usr/bin/podman", "attach", current_user.container_name])
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
            logging.info(
                f"starting background task with command `{cmd}` to continously read "
                "and forward pty output to client"
            )
            logging.info("task started")


def main():
    socketio.run(app, debug=True, port=8080, host="0.0.0.0")


if __name__ == "__main__":
    main()