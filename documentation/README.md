# Project Bermuda

Educational platform for University of Oregon students to practice cybersecurity skills.

Similar to “Hack the Box” or other CTF platforms, but more accessible to those who are new.

Securely give access to authorized users to vulnerable servers to learn some ethical hacking tools and practices.

## Authors 
**Made by Python Pirates**

Stephen Swanson - Alexandr Iapara - Emily Clauson - Jake Khal


## Installation

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install the required packages

Install required packages:
```bash
cd flask
pip install -r requirements.txt
```
Decrypt the credentials file and deploy the application:
```bash
cd flask/config
cp credentials.json.enc credentials.json
ansible-vault decrypt credentials.json
[Enter Secret Phrase]
cd ..
python3 routes.py
```
## Usage
Open the browser of your preference and enter the following URL:
```
localhost:5000
```
or
```
127.0.0.1:5000
```

## Technologies Used
Python, Flask, HTML, CSS, Ansible, MariaDB, Caddy, MSAL/OIDC Module, Azure


## License

[MIT](https://choosealicense.com/licenses/mit/)